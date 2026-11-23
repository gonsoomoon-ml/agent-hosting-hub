"""The custom guardrail's interceptor on the agent gateway: what it answers for each kind of call. The guard is swapped
for a fixed one, so nothing here calls AWS (the call of Amazon Bedrock Guardrails is checked against the service model
in tests/test_aws_calls.py)."""
import base64
import copy
import json
import re

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
    """A guard that records (text, source) of each check and answers as `guard` does (by default: blocks nothing,
    masks nothing)."""
    def __init__(self, guard=PASS):
        self.checked, self.guard = [], guard

    def __call__(self, text, source):
        self.checked.append((text, source))
        return self.guard(text, source)


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


def test_the_whole_request_is_checked_on_the_way_in_and_the_whole_answer_on_the_way_out():
    seen = Seen()
    handler(event(prompt="What is the spec of part P-100?"), None, guard=seen)
    handler(event(prompt="What is the spec of part P-100?", answer='{"answer": "M4 x 12 mm"}'), None, guard=seen)
    assert seen.checked == [("prompt\nWhat is the spec of part P-100?", "INPUT"), ('{"answer": "M4 x 12 mm"}', "OUTPUT")]


FALCON = lambda text, source: ("Project Falcon" in text, text)                           # blocks the code name only


@pytest.mark.parametrize("body", [
    '{"prompt": "hello", "context": "Project Falcon schedule"}',                    # another field of the request
    '{"prompt": "hello", "history": [{"text": "Project Falcon"}]}',                  # deeper in the document
    '{"prompt": "hello", "Project Falcon": 1}',                                     # a field name
    '{"prompt": "hello", "context": "\\u0050roject Falcon"}',                        # a JSON escape: read as its text
    '{"note": "\\u0050roject Falcon"}',                                              # no prompt, an escape
])
def test_a_blocked_word_outside_the_prompt_is_blocked(body):
    assert out_is_refused(handler(event(raw=b64(body)), None, guard=FALCON)), body


WORD = lambda text, source: (re.search(r"\bProject Falcon\b", text) is not None, text)  # the code name as whole words


def test_a_code_name_right_after_a_line_break_is_blocked():
    # the text checked holds the real line break, so the code name starts a word (not "\nProject", a backslash and n)
    body = json.dumps({"prompt": "Summarise the schedule.\nProject Falcon starts in May."})
    assert out_is_refused(handler(event(raw=b64(body)), None, guard=WORD))
    seen = Seen()
    handler(event(raw=b64(json.dumps({"prompt": "the schedule of Project\nFalcon\tnow"}))), None, guard=seen)
    assert seen.checked == [("prompt\nthe schedule of Project\nFalcon\tnow", "INPUT")]


@pytest.mark.parametrize("doc, checked", [
    ({"prompt": "hi", "history": [{"text": "x"}, ["Project Falcon"]]}, "prompt\nhi\nhistory\ntext\nx\nProject Falcon"),
    ({"prompt": "hi", "meta": {"tags": {"Project Falcon": True}}}, "prompt\nhi\nmeta\ntags\nProject Falcon"),
    ({"prompt": "hi", "Project Falcon": 1}, "prompt\nhi\nProject Falcon"),
], ids=["a value in a nested list", "a key of a nested object", "a key"])
def test_every_key_and_every_string_of_the_document_is_checked(doc, checked):
    # one line each, in the order of the document; numbers, true, false and null are not text
    seen = Seen()
    handler(event(raw=b64(json.dumps(doc))), None, guard=seen)
    assert seen.checked == [(checked, "INPUT")]
    assert out_is_refused(handler(event(raw=b64(json.dumps(doc))), None, guard=WORD))


def test_a_very_deep_document_is_checked_without_raising():
    # json.loads takes nesting far deeper than Python's recursion limit (1,000), so the walk must not recurse
    deep = '{"prompt": "hi", "deep": ' + "[" * 5_000 + '"Project Falcon"' + "]" * 5_000 + "}"
    assert json.loads(deep)
    seen = Seen()
    handler(event(raw=b64(deep)), None, guard=seen)
    assert seen.checked == [("prompt\nhi\ndeep\nProject Falcon", "INPUT")]
    assert out_is_refused(handler(event(raw=b64(deep)), None, guard=WORD))


def test_a_block_from_the_check_of_the_prompt_refuses_the_request():
    # the whole body is masked and not blocked; the second check, of the prompt alone, blocks
    prompt_only = lambda text, source: (text == "I am EMP-204817", MASK(text, source)[1])
    seen = Seen(prompt_only)
    out = handler(event(raw=b64(json.dumps({"prompt": "I am EMP-204817", "note": "x"}))), None, guard=seen)
    assert out_is_refused(out) and "transformedGatewayRequest" not in out["http"]
    assert seen.checked == [("prompt\nI am EMP-204817\nnote\nx", "INPUT"), ("I am EMP-204817", "INPUT")]


def test_masking_still_reads_the_prompt_path():
    # What goes on when the guardrail masks: in a body with a text prompt, only the prompt goes on masked and the rest
    # of the request as it came; a body without a prompt goes on masked as a whole; nothing masked, nothing changed.
    body = {"prompt": "I am EMP-204817", "note": "by EMP-204817"}
    out = handler(event(raw=b64(json.dumps(body))), None, guard=MASK)
    assert body_of(out["http"]["transformedGatewayRequest"]) == {"prompt": "I am {employee_id}", "note": "by EMP-204817"}
    out = handler(event(raw=b64('{"note": "by EMP-204817"}')), None, guard=MASK)
    assert text_of(out["http"]["transformedGatewayRequest"]) == '{"note": "by {employee_id}"}'
    assert handler(event(raw=b64('{"prompt": "hello", "note": "part P-100"}')), None, guard=MASK) == {
        "interceptorOutputVersion": "1.0", "http": {}}


def test_the_block_decision_reads_the_whole_body_and_masking_the_prompt():
    # Nothing to mask: one check, of the whole body. Something masked in it: then one check of the prompt.
    seen = Seen()
    handler(event(raw=b64('{"prompt": "hello", "note": "part P-100"}')), None, guard=seen)
    assert seen.checked == [("prompt\nhello\nnote\npart P-100", "INPUT")]
    seen = Seen(MASK)
    body = {"prompt": "I am EMP-204817", "note": "by EMP-204817"}
    handler(event(raw=b64(json.dumps(body))), None, guard=seen)
    assert seen.checked == [("prompt\nI am EMP-204817\nnote\nby EMP-204817", "INPUT"), ("I am EMP-204817", "INPUT")]
    seen = Seen()                                  # a JSON body is read decoded: an escape as the text it stands for
    handler(event(raw=b64('{"prompt": "\\ud55c\\uae00", "note": "\\u0050art"}')), None, guard=seen)
    assert seen.checked == [("prompt\n한글\nnote\nPart", "INPUT")]


@pytest.mark.parametrize("raw", [None, "", "not base64!", b64("not json"), b64("[1, 2]"), b64('{"no_prompt": 1}')])
def test_an_odd_request_body_never_raises(raw):
    out = handler(event(raw=raw), None, guard=PASS)
    assert out["interceptorOutputVersion"] == "1.0"
    assert out == {"interceptorOutputVersion": "1.0", "http": {}}         # nothing to hide: it goes on unchanged


@pytest.mark.parametrize("raw", [{"prompt": "hello"}, ["hello"], 7, b"not base64!", b64("not json").encode()],
                         ids=["dict", "list", "number", "bytes", "base64 bytes"])
def test_a_request_body_that_is_not_a_string_never_raises(raw):
    assert handler(event(raw=raw), None, guard=PASS) == {"interceptorOutputVersion": "1.0", "http": {}}
    answer = {"interceptorInputVersion": "1.0", "http": {"gatewayRequest": {"body": raw},          # the RESPONSE point
                                                         "gatewayResponse": {"statusCode": 200, "body": raw}}}
    assert handler(answer, None, guard=PASS) == {"interceptorOutputVersion": "1.0", "http": {}}


@pytest.mark.parametrize("http", ["not an object", ["a list"], {"gatewayRequest": "not an object"},
                                  {"gatewayRequest": ["a list"]},
                                  {"gatewayRequest": {"body": b64('{"prompt": "hi"}')}, "gatewayResponse": "not an object"}],
                         ids=["http", "http list", "gatewayRequest", "gatewayRequest list", "gatewayResponse"])
def test_an_http_part_that_is_not_an_object_never_raises(http):
    # taken as an agent call with no body: nothing to check, it goes on unchanged
    assert handler({"interceptorInputVersion": "1.0", "http": http}, None, guard=PASS) == {
        "interceptorOutputVersion": "1.0", "http": {}}


def test_a_json_body_nested_deeper_than_the_parser_goes_never_raises():
    deep = "[" * 100_000 + "]" * 100_000                    # json.loads raises RecursionError on it
    assert handler(event(raw=b64(deep)), None, guard=PASS) == {"interceptorOutputVersion": "1.0", "http": {}}
    seen = Seen()
    handler(event(raw=b64(deep)), None, guard=seen)
    assert seen.checked == [(deep, "INPUT")]                 # checked whole, as text
    assert out_is_refused(handler(event(raw=b64(deep + " Project Falcon")), None,
                                  guard=lambda text, source: ("Project Falcon" in text, text)))


def test_a_request_body_that_is_not_a_string_is_still_checked():
    # a JSON object is read as the document it is, bytes as the text they hold: the same checks as a string body
    out = handler(event(raw={"prompt": "I am EMP-204817", "n": 1}), None, guard=MASK)
    assert body_of(out["http"]["transformedGatewayRequest"]) == {"prompt": "I am {employee_id}", "n": 1}
    falcon = lambda text, source: ("Project Falcon" in text, text)                       # blocks the code name only
    for raw in (b64("Project Falcon, not json").encode(), b"Project Falcon, not json", {"prompt": "Project Falcon"}):
        assert out_is_refused(handler(event(raw=raw), None, guard=falcon)), raw
    seen = Seen()
    handler(event(raw=b'{"prompt": "hello"}'), None, guard=seen)
    assert seen.checked == [("prompt\nhello", "INPUT")]


def out_is_refused(out):
    r = out["http"].get("transformedGatewayResponse", {})
    return r.get("statusCode") == 403 and body_of(r) == {"error": MESSAGE}


@pytest.mark.parametrize("raw, checked", [
    ("not base64!", "not base64!"),                        # not base64: the body as it is
    (b64("not json"), "not json"),                         # base64, not JSON: the decoded text
])
def test_an_odd_request_body_is_checked_whole_as_text(raw, checked):
    seen = Seen()
    handler(event(raw=raw), None, guard=seen)
    assert seen.checked == [(checked, "INPUT")]


@pytest.mark.parametrize("raw, checked", [
    (b64("[1, 2]"), ""),                                   # JSON, not an object, no text in it
    (b64('{"no_prompt": 1}'), "no_prompt"),                # an object without a prompt: its keys and strings
    (b64('{"prompt": 7}'), "prompt"),                      # a prompt that is not text
    (b64('["Project", {"a": "b"}]'), "Project\na\nb"),     # a list: its strings, keys too
])
def test_an_odd_json_body_is_checked_by_its_keys_and_strings(raw, checked):
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
