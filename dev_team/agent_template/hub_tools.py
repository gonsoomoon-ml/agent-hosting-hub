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


def _post(url: str, headers: dict, body: str) -> str:
    """Send the request. A refusal (HTTP 4xx) is an answer too: its body says why."""
    req = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")


def parse_tool_response(text: str) -> str:
    """What the tool returned, or "ERROR: <why>" when the gateway refused the call or the tool failed."""
    for line in text.splitlines():                    # a streamed answer carries the JSON on a data: line
        if line.startswith("data:"):
            text = line[5:].strip()
    try:
        doc = json.loads(text)
    except ValueError:
        return text[:1000]
    if doc.get("error"):
        return "ERROR: " + str(doc["error"].get("message"))[:500]
    result = doc.get("result") or {}
    out = " ".join(part.get("text", "") for part in result.get("content") or [])[:2000]
    return ("ERROR: " + out) if result.get("isError") else out


def call_tool(tool_id: str, arguments: dict) -> str:
    """Call a tool by its catalog name (<Target>___<tool>). Returns its text, or "ERROR: <message>"."""
    url, region = os.environ["TOOL_GATEWAY_URL"], os.environ["HUB_REGION"]
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool_id, "arguments": arguments}})
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    request = AWSRequest(method="POST", url=url, data=body, headers=headers)
    credentials = boto3.Session(region_name=region).get_credentials().get_frozen_credentials()
    SigV4Auth(credentials, SERVICE, region).add_auth(request)
    return parse_tool_response(_post(url, dict(request.headers), body))
