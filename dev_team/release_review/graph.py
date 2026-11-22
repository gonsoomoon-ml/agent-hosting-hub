"""The release review as a LangGraph graph with a fixed flow:
read_change -> check_rules -> file_request -> report.
Only check_rules asks the model; only file_request calls a tool."""
import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

FILE_TOOL = "Release___file_review_request"

# The release rules, in one place. The model judges a change against exactly these.
RELEASE_RULES = [
    "Every change goes through the canary stage before full rollout.",
    "Every change has a rollback plan.",
    "Every change has passing tests.",
]

SYSTEM_PROMPT = (
    "You review a change description against these release rules:\n"
    + "\n".join(f"{i}. {rule}" for i, rule in enumerate(RELEASE_RULES, 1))
    + "\nIf every rule is met, answer exactly: OK\n"
    "If a rule is broken, answer: VIOLATION: <the broken rule in a few words>\n"
    "Answer with nothing else."
)


class State(TypedDict, total=False):
    prompt: str
    verdict: str
    answer: str
    tools_used: list


def _change_id(prompt: str) -> str:
    match = re.search(r"\b[A-Z]{1,5}-\d+\b", prompt)
    return match.group(0) if match else "unknown"


def build(call_tool, ask_model):
    """call_tool(tool_id, arguments) -> str and ask_model(system, user) -> str are passed in, so tests give fakes."""

    def read_change(state: State) -> State:
        return {"prompt": state.get("prompt", "").strip(), "tools_used": []}

    def check_rules(state: State) -> State:
        try:
            verdict = ask_model(SYSTEM_PROMPT, state["prompt"]).strip()
        except Exception as e:      # a model failure must not look like "no violation"
            verdict = f"ERROR: the model could not check the rules: {type(e).__name__}: {e}"
        return {"verdict": verdict}

    def file_request(state: State) -> State:
        if not state["verdict"].startswith("VIOLATION"):
            return {}
        reason = state["verdict"].partition(":")[2].strip() or "release rule broken"
        text = call_tool(FILE_TOOL, {"change_id": _change_id(state["prompt"]), "summary": reason[:200]})
        return {"tools_used": state["tools_used"] + [FILE_TOOL], "answer": text}      # report reads the tool's text

    def report(state: State) -> State:
        verdict = state["verdict"]
        if verdict.startswith("ERROR"):
            return {"answer": verdict}
        if not verdict.startswith("VIOLATION"):
            return {"answer": verdict}
        text = state["answer"]
        if text.startswith("ERROR"):
            return {"answer": f"{verdict} The review request could not be filed: {text}"}
        try:
            request_id = json.loads(text)["request_id"]
        except (ValueError, KeyError, TypeError):
            return {"answer": f"{verdict} The review request could not be filed: unexpected answer: {text[:200]}"}
        return {"answer": f"{verdict} Review request: {request_id}"}

    g = StateGraph(State)
    nodes = [("read_change", read_change), ("check_rules", check_rules), ("file_request", file_request), ("report", report)]
    for name, fn in nodes:
        g.add_node(name, fn)
    path = [START] + [name for name, _ in nodes] + [END]      # the fixed order
    for a, b in zip(path, path[1:]):
        g.add_edge(a, b)
    return g.compile()
