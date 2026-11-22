import importlib.util
import json
import pathlib

import pytest

spec = importlib.util.spec_from_file_location("hub_tools", pathlib.Path("dev_team/agent_template/hub_tools.py"))
hub_tools = importlib.util.module_from_spec(spec); spec.loader.exec_module(hub_tools)


def test_tool_text_and_refusal_are_told_apart():
    ok = '{"jsonrpc":"2.0","id":1,"result":{"isError":false,"content":[{"type":"text","text":"{\\"spec\\":\\"M4\\"}"}]}}'
    no = '{"jsonrpc":"2.0","id":1,"error":{"code":-32002,"message":"Tool Execution Denied: not allowed"}}'
    assert hub_tools.parse_tool_response(ok) == '{"spec":"M4"}'
    assert hub_tools.parse_tool_response(no) == "ERROR: Tool Execution Denied: not allowed"
    assert hub_tools.parse_tool_response('event: message\ndata: ' + ok) == '{"spec":"M4"}'


def test_a_tool_that_reports_an_error_reads_as_an_error():
    text = '{"result":{"isError":true,"content":[{"type":"text","text":"no such part"}]}}'
    assert hub_tools.parse_tool_response(text) == "ERROR: no such part"


def test_call_tool_sends_a_signed_tools_call_to_the_gateway(monkeypatch):
    monkeypatch.setenv("TOOL_GATEWAY_URL", "https://gw.example.com/mcp")
    monkeypatch.setenv("HUB_REGION", "us-west-2")
    sent = {}

    class Creds:
        def get_frozen_credentials(self):
            return object()

    class Session:
        def __init__(self, region_name=None):
            sent["region"] = region_name

        def get_credentials(self):
            return Creds()

    def fake_sign(creds, service, region):
        sent["service"], sent["sign_region"] = service, region
        return type("Auth", (), {"add_auth": lambda self, req: req.headers.__setitem__("Authorization", "signed")})()

    def fake_post(url, headers, body):
        sent.update(url=url, headers=headers, body=json.loads(body))
        return '{"result":{"content":[{"type":"text","text":"M4"}]}}'

    monkeypatch.setattr(hub_tools.boto3, "Session", Session)
    monkeypatch.setattr(hub_tools, "SigV4Auth", fake_sign)
    monkeypatch.setattr(hub_tools, "_post", fake_post)
    assert hub_tools.call_tool("Parts___get_part_spec", {"part_id": "P-100"}) == "M4"
    assert sent["url"] == "https://gw.example.com/mcp"
    assert sent["service"] == "bedrock-agentcore" and sent["sign_region"] == "us-west-2"
    assert sent["headers"]["Authorization"] == "signed"
    assert sent["body"]["method"] == "tools/call"
    assert sent["body"]["params"] == {"name": "Parts___get_part_spec", "arguments": {"part_id": "P-100"}}


def test_call_tool_needs_the_gateway_address(monkeypatch):
    monkeypatch.delenv("TOOL_GATEWAY_URL", raising=False)
    with pytest.raises(KeyError):
        hub_tools.call_tool("Parts___get_part_spec", {})
