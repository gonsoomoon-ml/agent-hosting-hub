"""quality_agent: answers questions about inspection results. A Strands agent (a ReAct loop) with two shared tools,
both called through the hub's tool gateway."""
import os

from strands import Agent, tool
from strands.models import BedrockModel

from hub_tools import call_tool, error_text

SYSTEM_PROMPT = """You are a quality-analysis assistant. You answer questions about inspection results and part specifications.

Use get_inspection_data to read an inspection case (ids look like Q-1001) and get_part_spec to read a part (ids look like P-100).
Answer only from what the tools return. Never invent a value, an id or a result.
When you report an inspection result, write the inspector's employee ID exactly as the tool gives it. Do not shorten, rephrase or guess it.
If a tool answer starts with "ERROR:", the call was refused or failed. Tell the user so plainly, give the reason in the answer, and do not make up the data.
If the question needs an id you were not given, ask for it."""

_model = None


@tool
def get_inspection_data(case_id: str) -> str:
    """Read one inspection case: its part, its result and the inspector.

    Args:
        case_id: Inspection case id, for example Q-1001.
    """
    return call_tool("Quality___get_inspection_data", {"case_id": case_id})


@tool
def get_part_spec(part_id: str) -> str:
    """Read the specification of a part.

    Args:
        part_id: Part id, for example P-100.
    """
    return call_tool("Parts___get_part_spec", {"part_id": part_id})


TOOLS = [get_inspection_data, get_part_spec]
CATALOG_NAMES = {"get_inspection_data": "Quality___get_inspection_data", "get_part_spec": "Parts___get_part_spec"}


def _get_model() -> BedrockModel:
    """Bedrock in HUB_REGION with MODEL_ID (an inference profile ID). Made on first use, so importing needs no AWS."""
    global _model
    if _model is None:
        _model = BedrockModel(model_id=os.environ["MODEL_ID"], region_name=os.environ["HUB_REGION"],
                              temperature=0, max_tokens=1000)
    return _model


def new_agent() -> Agent:
    """A fresh agent for each question, so one caller's conversation never reaches another's."""
    return Agent(model=_get_model(), tools=TOOLS, system_prompt=SYSTEM_PROMPT, callback_handler=None)


def tools_called(messages: list) -> list:
    """The catalog names of the tools the model called, in order, read from the conversation Strands recorded."""
    return [CATALOG_NAMES.get(block["toolUse"]["name"], block["toolUse"]["name"]) for m in messages if m.get("role") == "assistant"
            for block in m.get("content", []) if "toolUse" in block]


def ask_once(prompt: str) -> tuple[str, list]:
    """One question to a fresh agent: its answer and the tools the model called."""
    try:
        agent = new_agent()
        result = agent(prompt)
    except Exception as e:      # missing setting, model access, throttling: told to the caller, not raised
        return f"ERROR: {error_text(e)}", []
    return str(result).strip(), tools_called(agent.messages)


# --- demo incident: asks again until the result is confirmed ---
# The demo's incident version. While an inspection result is not in yet (PENDING), the agent asks the same question
# again from the start, as often as it can: the retry has lost its limit on the count. RETRY_SECONDS is not part of
# that story. It is the demo's safety: a caller that gives up does not end the loop, so this limit is what ends a loop
# nobody stops, and it bounds what one incident costs.
import time  # noqa: E402 (inside the block, so the rest of the file stays the base file)


def ask_until_confirmed(prompt: str) -> tuple[str, list]:
    """Ask, and while the answer says PENDING, ask again from the start: a fresh agent each time, so each round calls
    the model again and, for an inspection case, the tool again. Stops when the answer no longer says PENDING or when
    RETRY_SECONDS (environment, default 600) have passed since the first question. Returns the last answer."""
    deadline = time.monotonic() + float(os.environ.get("RETRY_SECONDS") or 600)
    answer, used = ask_once(prompt)
    again = 0
    while "PENDING" in answer.upper() and time.monotonic() < deadline:     # the model may write it in lower case
        again += 1
        print(f"asking again ({again})", flush=True)
        answer, used = ask_once(prompt)
    return answer, used


# --- end of the demo incident ---
def run(prompt: str) -> tuple[str, list]:
    if not prompt.strip():
        return "ERROR: empty prompt", []
    return ask_until_confirmed(prompt)
