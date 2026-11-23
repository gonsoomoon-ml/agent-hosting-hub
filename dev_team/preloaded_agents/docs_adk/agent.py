"""docs_adk: answers questions about the company's design standards. A Google ADK agent (LlmAgent) with one tool,
find_standard, that runs in the agent's own process: no call goes through the hub's tool gateway, so the application
names no hub tool. The model is Amazon Bedrock (MODEL_ID in HUB_REGION), called through the Converse API by a small ADK
model class (BedrockConverse), so the agent needs no package beyond google-adk and boto3."""
import asyncio
import json
import os
import re

import boto3
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm, LlmCapabilities, LlmRequest, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from hub_tools import error_text

APP, USER = "docs_adk", "caller"
MAX_TOKENS = 1000
INSTRUCTION = """You answer questions about the company's design standards.
Use find_standard to look up the standard for a topic, and answer only from what it returns. Name the standard's ID (like STD-01).
If no standard covers the question, say so plainly and name the topics there are standards for. Never invent a standard or a rule."""

# The example standards. In a real hub they would come from a document store; here they are part of the code.
STANDARDS = (
    {"id": "STD-01", "title": "API versioning", "keywords": ("api", "apis", "version", "versions", "versioning",
                                                           "endpoint", "endpoints", "breaking"),
     "text": "Every public HTTP API carries its major version in the path (/v1/...). A breaking change gets a new major "
             "version, and the previous one is served for at least 6 months after the new one is released."},
    {"id": "STD-02", "title": "Logging", "keywords": ("log", "logs", "logging"),
     "text": "Services write one JSON object per line with the fields timestamp (UTC, ISO 8601), level, service and "
             "request_id. No secret, token or personal data goes into a log line."},
    {"id": "STD-03", "title": "Timeouts and retries", "keywords": ("timeout", "timeouts", "retry", "retries", "backoff",
                                                                 "wait"),
     "text": "Every outbound call sets a timeout of at most 10 seconds. Retries use exponential backoff with jitter and "
             "stop after 3 attempts; a call that changes data is retried only when it is idempotent."},
)

_client = None


def find_standard(topic: str) -> str:
    """Find the company's design standard for a topic.

    Args:
        topic: What the question is about, for example "API versioning", "logging" or "timeouts".
    """
    words = set(re.findall(r"[a-z0-9]+", topic.lower()))
    found = [s for s in STANDARDS if words & set(s["keywords"])]
    if not found:
        known = ", ".join(f"{s['title']} ({s['id']})" for s in STANDARDS)
        return f"No design standard covers '{topic}'. There are standards for: {known}."
    return "\n".join(f"{s['id']} {s['title']}: {s['text']}" for s in found)


def _bedrock(region: str):
    """The Bedrock client, made on first use, so importing needs no AWS."""
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=region)
    return _client


def _text(instruction) -> str:
    """ADK's system instruction (a string, or content with text parts) as plain text."""
    if isinstance(instruction, str):
        return instruction
    parts = getattr(instruction, "parts", None) or []
    return "".join(p.text or "" for p in parts)


def _block(part: types.Part) -> dict | None:
    """One part of ADK's conversation as a Converse content block; a thought or an empty part is left out."""
    if part.thought:
        return None
    if part.text:
        return {"text": part.text}
    if part.function_call:
        call = part.function_call
        return {"toolUse": {"toolUseId": call.id, "name": call.name, "input": call.args or {}}}
    if part.function_response:
        result = part.function_response.response or {}
        text = result["result"] if set(result) == {"result"} and isinstance(result["result"], str) else json.dumps(result)
        return {"toolResult": {"toolUseId": part.function_response.id, "content": [{"text": text}]}}
    return None


def _tool_spec(declaration: types.FunctionDeclaration) -> dict:
    schema = declaration.parameters_json_schema or {"type": "object", "properties": {}}
    return {"toolSpec": {"name": declaration.name, "description": declaration.description or declaration.name,
                         "inputSchema": {"json": schema}}}


def converse_request(model: str, request: LlmRequest) -> dict:
    """ADK's request as the arguments of one Converse call: the conversation (turns of the same role joined, as
    Converse takes turns that alternate), the system instruction and the tool declarations."""
    messages = []
    for content in request.contents:
        role = "assistant" if content.role == "model" else "user"
        blocks = [b for b in (_block(p) for p in content.parts or []) if b]
        if not blocks:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += blocks
        else:
            messages.append({"role": role, "content": blocks})
    out = {"modelId": model, "messages": messages, "inferenceConfig": {"maxTokens": MAX_TOKENS, "temperature": 0}}
    system = _text(request.config.system_instruction)        # LlmRequest always has a config
    if system:
        out["system"] = [{"text": system}]
    tools = [_tool_spec(d) for t in (request.config.tools or []) for d in (getattr(t, "function_declarations", None) or [])]
    if tools:
        out["toolConfig"] = {"tools": tools}
    return out


def llm_response(answer: dict) -> LlmResponse:
    """A Converse answer as ADK's response: its text and tool calls, and the token counts."""
    parts = []
    for block in answer["output"]["message"]["content"]:
        if "text" in block:
            parts.append(types.Part(text=block["text"]))
        elif "toolUse" in block:
            use = block["toolUse"]
            parts.append(types.Part(function_call=types.FunctionCall(id=use["toolUseId"], name=use["name"],
                                                                     args=use.get("input") or {})))
    usage = answer.get("usage") or {}
    return LlmResponse(content=types.Content(role="model", parts=parts),
                       usage_metadata=types.GenerateContentResponseUsageMetadata(
                           prompt_token_count=usage.get("inputTokens"), candidates_token_count=usage.get("outputTokens"),
                           total_token_count=usage.get("totalTokens")) if usage else None)


class BedrockConverse(BaseLlm):
    """An ADK model that calls Amazon Bedrock's Converse API with boto3: each of ADK's requests is one Converse call,
    and its answer one response (no streaming)."""
    region: str

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        answer = await asyncio.to_thread(_bedrock(self.region).converse, **converse_request(self.model, llm_request))
        yield llm_response(answer)


def new_agent() -> LlmAgent:
    return LlmAgent(name=APP, model=BedrockConverse(model=os.environ["MODEL_ID"], region=os.environ["HUB_REGION"]),
                    instruction=INSTRUCTION, tools=[find_standard])


async def _ask(prompt: str) -> tuple[str, list]:
    """One question in a new session of a fresh runner, so one caller's conversation never reaches another's: the
    final answer's text and the names of the tools the model called."""
    runner = InMemoryRunner(agent=new_agent(), app_name=APP)
    session = await runner.session_service.create_session(app_name=APP, user_id=USER)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    answer, used = [], []
    async for event in runner.run_async(user_id=USER, session_id=session.id, new_message=message):
        used += [call.name for call in event.get_function_calls()]
        if event.is_final_response() and event.content:
            answer += [p.text for p in event.content.parts or [] if p.text and not p.thought]
    return " ".join(answer).strip(), used


def run(prompt: str) -> tuple[str, list]:
    if not prompt.strip():
        return "ERROR: empty prompt", []
    try:
        return asyncio.run(_ask(prompt))
    except Exception as e:      # missing setting, model access, throttling: told to the caller, not raised
        return f"ERROR: {error_text(e)}", []
