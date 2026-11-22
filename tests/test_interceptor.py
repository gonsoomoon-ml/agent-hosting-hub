"""The custom guardrail's interceptor on the agent gateway: what it answers for each kind of call. The guard is swapped
for a fixed one, so nothing here calls AWS (the call of Amazon Bedrock Guardrails is checked against the service model
in tests/test_aws_calls.py)."""
import base64
import copy
import json

import pytest

from platform_team.custom_guardrail.interceptor_lambda import MESSAGE, handler


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def event(prompt=None, answer=None, raw=None):
    """An agent call as the gateway sends it: bodies are base64. The request carries {"prompt": prompt}, or `raw` as
    its body as it is; with `answer` it is the RESPONSE point, which carries the agent's answer as well."""
    body = raw if prompt is None else b64(json.dumps({"prompt": prompt}))
    http = {"gatewayRequest": {"path": "/QualityAgent/invocations", "body": body}}
    if answer is not None:
        http["gatewayResponse"] = {"statusCode": 200, "body": b64(answer)}
    return {"interceptorInputVersion": "1.0", "http": http}


def body_of(part):
    return json.loads(base64.b64decode(part["body"]))


def text_of(part):
    return base64.b64decode(part["body"]).decode("utf-8")


BLOCK = lambda text, source: (True, text)
MASK = lambda text, source: (False, text.replace("EMP-204817", "{employee_id}"))
PASS = lambda text, source: (False, text)


class Seen:
    """A guard that blocks nothing, masks nothing and records (text, source) of each check."""
    def __init__(self):
        self.checked = []

    def __call__(self, text, source):
        self.checked.append((text, source))
        return False, text


def test_a_blocked_prompt_is_refused_with_403():
    out = handler(event(prompt="the schedule of Project Falcon"), None, guard=BLOCK)
    r = out["http"]["transformedGatewayResponse"]
    assert r["statusCode"] == 403 and body_of(r) == {"error": "Blocked by the company guardrail (interceptor)."}
    assert MESSAGE == "Blocked by the company guardrail (interceptor)." and out["interceptorOutputVersion"] == "1.0"
    assert "transformedGatewayRequest" not in out["http"]                 # the call ends here


def test_a_masked_prompt_goes_on_in_its_masked_form():
    out = handler(event(prompt="I am EMP-204817"), None, guard=MASK)
    assert body_of(out["http"]["transformedGatewayRequest"]) == {"prompt": "I am {employee_id}"}
    assert "transformedGatewayResponse" not in out["http"]


def test_a_masked_answer_comes_back_masked():
    out = handler(event(prompt="who?", answer='{"answer": "inspected by EMP-204817"}'), None, guard=MASK)
    answer = base64.b64decode(out["http"]["transformedGatewayResponse"]["body"]).decode()
    assert "{employee_id}" in answer and "EMP-204817" not in answer
    assert json.loads(answer) == {"answer": "inspected by {employee_id}"}


def test_a_blocked_answer_is_refused_with_403():
    out = handler(event(prompt="who?", answer='{"answer": "Project Falcon starts in May"}'), None, guard=BLOCK)
    r = out["http"]["transformedGatewayResponse"]
    assert r["statusCode"] == 403 and body_of(r) == {"error": MESSAGE}


def test_a_call_with_nothing_to_hide_passes_unchanged():
    assert handler(event(prompt="What is the spec of part P-100?"), None, guard=PASS) == {"interceptorOutputVersion": "1.0", "http": {}}
    assert handler(event(prompt="What is the spec of part P-100?", answer='{"answer": "M4 x 12 mm"}'), None,
                   guard=PASS) == {"interceptorOutputVersion": "1.0", "http": {}}


def test_the_prompt_is_checked_on_the_way_in_and_the_whole_answer_on_the_way_out():
    seen = Seen()
    handler(event(prompt="What is the spec of part P-100?"), None, guard=seen)
    handler(event(prompt="What is the spec of part P-100?", answer='{"answer": "M4 x 12 mm"}'), None, guard=seen)
    assert seen.checked == [("What is the spec of part P-100?", "INPUT"), ('{"answer": "M4 x 12 mm"}', "OUTPUT")]


@pytest.mark.parametrize("raw", [None, "", "not base64!", b64("not json"), b64("[1, 2]"), b64('{"no_prompt": 1}')])
def test_an_odd_request_body_never_raises(raw):
    out = handler(event(raw=raw), None, guard=PASS)
    assert out["interceptorOutputVersion"] == "1.0"
    assert out == {"interceptorOutputVersion": "1.0", "http": {}}         # nothing to hide: it goes on unchanged


@pytest.mark.parametrize("raw, checked", [
    ("not base64!", "not base64!"),                        # not base64: the body as it is
    (b64("not json"), "not json"),                         # base64, not JSON: the decoded text
    (b64("[1, 2]"), "[1, 2]"),                             # JSON, not an object: the whole body
    (b64('{"no_prompt": 1}'), '{"no_prompt": 1}'),         # an object without a prompt: the whole body
    (b64('{"prompt": 7}'), '{"prompt": 7}'),               # a prompt that is not text: the whole body
])
def test_an_odd_request_body_is_checked_whole_as_text(raw, checked):
    seen = Seen()
    handler(event(raw=raw), None, guard=seen)
    assert seen.checked == [(checked, "INPUT")]


def test_an_odd_request_body_is_still_checked_as_text():
    assert "transformedGatewayResponse" in handler(event(raw=b64("Project Falcon, not json")), None, guard=BLOCK)["http"]
    falcon = lambda text, source: ("Project Falcon" in text, text)                       # blocks the code name only
    assert "transformedGatewayResponse" in handler(event(raw="Project Falcon, not json"), None, guard=falcon)["http"]
    assert handler(event(raw=b64("part P-100, not json")), None, guard=falcon) == {"interceptorOutputVersion": "1.0", "http": {}}


@pytest.mark.parametrize("raw, masked", [
    (b64("I am EMP-204817"), "I am {employee_id}"),                                      # not JSON
    ("I am EMP-204817", "I am {employee_id}"),                                           # not base64
    (b64('{"note": "by EMP-204817"}'), '{"note": "by {employee_id}"}'),                  # no prompt
])
def test_an_odd_request_body_goes_on_masked_as_a_whole(raw, masked):
    out = handler(event(raw=raw), None, guard=MASK)
    assert text_of(out["http"]["transformedGatewayRequest"]) == masked


def test_an_event_that_is_not_an_agent_call_passes():
    assert handler({"mcp": {}}, None, guard=BLOCK) == {"interceptorOutputVersion": "1.0"}


def test_the_same_event_twice_gives_the_same_answer():
    for e, guard in ((event(prompt="I am EMP-204817"), MASK), (event(prompt="who?", answer="by EMP-204817"), MASK),
                     (event(prompt="Project Falcon"), BLOCK), (event(raw=b64("I am EMP-204817")), MASK)):
        before = copy.deepcopy(e)
        first = handler(e, None, guard=guard)
        assert handler(e, None, guard=guard) == first and e == before         # and the event is not changed


def test_a_swapped_guard_makes_no_aws_client(monkeypatch):
    """The Amazon Bedrock client is made when the real guard first needs it, not when the module is loaded."""
    monkeypatch.setattr("boto3.client", lambda *a, **kw: pytest.fail("an AWS client was made"))
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    assert handler(event(prompt="hello"), None, guard=PASS) == {"interceptorOutputVersion": "1.0", "http": {}}
