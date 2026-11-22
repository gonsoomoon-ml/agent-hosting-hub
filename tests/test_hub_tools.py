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
        return 200, '{"result":{"content":[{"type":"text","text":"M4"}]}}'

    monkeypatch.setattr(hub_tools.boto3, "Session", Session)
    monkeypatch.setattr(hub_tools, "SigV4Auth", fake_sign)
    monkeypatch.setattr(hub_tools, "_post", fake_post)
    assert hub_tools.call_tool("Parts___get_part_spec", {"part_id": "P-100"}) == "M4"
    assert sent["url"] == "https://gw.example.com/mcp"
    assert sent["service"] == "bedrock-agentcore" and sent["sign_region"] == "us-west-2"
    assert sent["headers"]["Authorization"] == "signed"
    assert sent["body"]["method"] == "tools/call"
    assert sent["body"]["params"] == {"name": "Parts___get_part_spec", "arguments": {"part_id": "P-100"}}


def _env(monkeypatch):
    monkeypatch.setenv("TOOL_GATEWAY_URL", "https://gw.example.com/mcp")
    monkeypatch.setenv("HUB_REGION", "us-west-2")
    monkeypatch.setattr(hub_tools.boto3, "Session", lambda region_name=None: type(
        "S", (), {"get_credentials": lambda self: type("C", (), {"get_frozen_credentials": lambda self: object()})()})())
    monkeypatch.setattr(hub_tools, "SigV4Auth", lambda *a: type("A", (), {"add_auth": lambda self, r: None})())


def test_missing_gateway_address_is_an_error_text(monkeypatch):
    monkeypatch.delenv("TOOL_GATEWAY_URL", raising=False)
    assert hub_tools.call_tool("Parts___get_part_spec", {}) == "ERROR: TOOL_GATEWAY_URL is not set"


def test_missing_region_is_an_error_text(monkeypatch):
    monkeypatch.setenv("TOOL_GATEWAY_URL", "https://gw.example.com/mcp")
    monkeypatch.delenv("HUB_REGION", raising=False)
    assert hub_tools.call_tool("x", {}) == "ERROR: HUB_REGION is not set"


def test_an_http_refusal_without_json_rpc_is_an_error(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hub_tools, "_post", lambda u, h, b: (403, '{"message":"not authorized"}'))
    out = hub_tools.call_tool("x", {})
    assert out.startswith("ERROR: HTTP 403") and "not authorized" in out


def test_an_http_refusal_with_json_rpc_error_keeps_its_message(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(hub_tools, "_post", lambda u, h, b: (403, '{"error":{"message":"Denied"}}'))
    assert hub_tools.call_tool("x", {}) == "ERROR: Denied"


def test_network_failure_and_missing_credentials_are_error_texts(monkeypatch):
    _env(monkeypatch)

    def down(u, h, b):
        raise TimeoutError("timed out")
    monkeypatch.setattr(hub_tools, "_post", down)
    assert hub_tools.call_tool("x", {}) == "ERROR: could not reach the tool gateway: TimeoutError: timed out"
    monkeypatch.setattr(hub_tools.boto3, "Session", lambda region_name=None: type("S", (), {"get_credentials": lambda self: None})())
    assert hub_tools.call_tool("x", {}) == "ERROR: no AWS credentials to sign the call"


def test_non_json_and_non_object_bodies_are_not_empty_successes():
    assert hub_tools.parse_tool_response("oops") == "ERROR: unexpected answer: oops"
    assert hub_tools.parse_tool_response("[1]").startswith("ERROR: unexpected answer")
    assert hub_tools.parse_tool_response('"x"').startswith("ERROR: unexpected answer")


def test_the_result_wins_over_other_stream_events():
    ok = '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"M4"}]}}'
    stream = 'data: ' + ok + '\n\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n'
    assert hub_tools.parse_tool_response(stream) == "M4"
