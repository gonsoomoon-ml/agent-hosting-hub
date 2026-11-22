"""How an agent calls the hub's shared tools: MCP `tools/call` over HTTP to the tool gateway, signed with SigV4.
No agent framework and no package beyond boto3. The Runtime sets TOOL_GATEWAY_URL and HUB_REGION."""
import json
import os
import urllib.error
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

SERVICE = "bedrock-agentcore"      # the name the gateway expects in the signature


def _post(url: str, headers: dict, body: str) -> tuple[int, str]:
    """Send the request. Returns the HTTP status and the body; a refusal (HTTP 4xx) is an answer too."""
    req = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _documents(text: str) -> list:
    """The JSON documents in an answer: the body itself, or the data: lines of an event stream."""
    lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")] or [text]
    docs = []
    for line in lines:
        try:
            docs.append(json.loads(line))
        except ValueError:
            pass
    return docs


def parse_tool_response(text: str) -> str:
    """What the tool returned, or "ERROR: <why>" when the gateway refused the call or the tool failed."""
    docs = _documents(text)
    # the answer is the first event that carries a result or an error; a progress notification carries neither
    doc = next((d for d in docs if isinstance(d, dict) and ("result" in d or "error" in d)), None)
    if doc is None:
        return "ERROR: unexpected answer: " + text[:300]
    if doc.get("error"):
        return "ERROR: " + str((doc["error"] or {}).get("message"))[:500]
    result = doc.get("result") or {}
    out = " ".join(part.get("text", "") for part in result.get("content") or [])[:2000]
    return ("ERROR: " + out) if result.get("isError") else out


def call_tool(tool_id: str, arguments: dict) -> str:
    """Call a tool by its catalog name (<Target>___<tool>). Returns its text, or "ERROR: <message>".
    It does not raise: a failure is text the agent (or its model) can read."""
    for name in ("TOOL_GATEWAY_URL", "HUB_REGION"):
        if not os.environ.get(name):
            return f"ERROR: {name} is not set"
    url, region = os.environ["TOOL_GATEWAY_URL"], os.environ["HUB_REGION"]
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool_id, "arguments": arguments}})
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        credentials = boto3.Session(region_name=region).get_credentials()
        if credentials is None:
            return "ERROR: no AWS credentials to sign the call"
        request = AWSRequest(method="POST", url=url, data=body, headers=headers)
        SigV4Auth(credentials.get_frozen_credentials(), SERVICE, region).add_auth(request)
        status, text = _post(url, dict(request.headers), body)
    except Exception as e:      # network, timeout, signing: told to the agent, not raised inside it
        return f"ERROR: could not reach the tool gateway: {type(e).__name__}: {e}"
    answer = parse_tool_response(text)
    if status >= 400 and not answer.startswith("ERROR"):
        return f"ERROR: HTTP {status} {text[:300]}"
    if status >= 400 and answer.startswith("ERROR: unexpected answer"):
        return f"ERROR: HTTP {status} {text[:300]}"
    return answer
