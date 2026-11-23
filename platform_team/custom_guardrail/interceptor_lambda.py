"""Gateway interceptor on the agent gateway: calls the custom guardrail (Amazon Bedrock Guardrails, ApplyGuardrail)
on every request and every answer. A blocked text ends the call with the interceptor's own response.
A masked text goes on in its masked form. To use the company's own guardrail, change guard().

Whether a request is blocked is decided on its whole body: a JSON body as its document written again without
escapes, so every string in it counts (field names too); any other body as it came. What is masked is the prompt
when the body is a JSON object with a text "prompt", and only the prompt goes on masked; any other body (not base64,
not JSON, not an object, no prompt) goes on whole in its masked form. An answer is always checked whole, as the text
the agent sent (a JSON answer with its escapes as they are). A body that is not a string is read as text first
(unb64), a part of the event that is not an object is taken as one with no body, and a JSON body nested deeper than
the parser goes is read as text, so none of these makes the handler raise. The log line says only where, whether
blocked and whether masked: never the text.
"""
import base64
import json
import os

import boto3

MESSAGE = "Blocked by the company guardrail (interceptor)."
V = "interceptorOutputVersion"
_runtime = None             # the bedrock-runtime client, made on first use (the tests swap guard and make none)


def _client():
    global _runtime
    if _runtime is None:
        _runtime = boto3.client("bedrock-runtime")
    return _runtime


def guard(text, source):
    """Return (blocked, text after masking)."""
    if not text:
        return False, text
    r = _client().apply_guardrail(guardrailIdentifier=os.environ["GUARDRAIL_ID"],
                                  guardrailVersion=os.environ.get("GUARDRAIL_VERSION", "DRAFT"), source=source,
                                  content=[{"text": {"text": text}}])
    blocked = '"action": "BLOCKED"' in json.dumps(r.get("assessments", []))
    masked = r["outputs"][0]["text"] if r.get("action") == "GUARDRAIL_INTERVENED" and r.get("outputs") and not blocked else text
    return blocked, masked


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(text):
    """The body as text. A body that is not base64 of UTF-8 text is taken as it is (line breaks in base64 are fine).
    A body that is not a string is text too, so it is checked like one: bytes as the UTF-8 text they hold, any other
    value (a JSON object, a list, a number) as its JSON text."""
    if not text:
        return ""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    elif not isinstance(text, str):
        return json.dumps(text, default=str)
    try:
        return base64.b64decode("".join(text.split()), validate=True).decode("utf-8")
    except ValueError:                  # binascii.Error and UnicodeDecodeError are both ValueErrors
        return text


def _object(part):
    """A part of the event as an object: a part that is not one is taken as an empty object (no body)."""
    return part if isinstance(part, dict) else {}


def _read(raw):
    """(the request's JSON document, its prompt, the whole body), or (None, the body as it came, the whole body) when
    the body has no text prompt. The block decision reads the whole body: a JSON body as its document written again
    without escapes (every string in it, field names too, as the text it holds); any other body as it came. Masking
    reads the prompt, or the body as it came."""
    try:
        doc = json.loads(raw)
        whole = json.dumps(doc, ensure_ascii=False)
    except (ValueError, RecursionError):     # not JSON, or nested deeper than the parser goes: text as it came
        return None, raw, raw
    if isinstance(doc, dict) and isinstance(doc.get("prompt"), str):
        return doc, doc["prompt"], whole
    return None, raw, whole


def refuse():
    return {V: "1.0", "http": {"transformedGatewayResponse": {
        "statusCode": 403, "contentType": "application/json", "body": b64(json.dumps({"error": MESSAGE}))}}}


def handler(event, context, guard=guard):
    h = event.get("http")
    if h is None:                                                       # not an agent call: pass it on unchanged
        return {V: "1.0"}
    h = _object(h)
    req, resp = _object(h.get("gatewayRequest")), h.get("gatewayResponse")
    if resp is None:                                                    # REQUEST: the user's prompt
        doc, prompt, whole = _read(unb64(req.get("body")))
        blocked, masked = guard(whole, "INPUT")                        # blocked by any text of the request
        if not blocked and whole != prompt:     # masked: the prompt, checked again when the whole body had a mask
            blocked, masked = guard(prompt, "INPUT") if masked != whole else (False, prompt)
        print(json.dumps({"point": "REQUEST", "blocked": blocked, "masked": masked != prompt}))
        if blocked:
            return refuse()
        if masked != prompt:
            if doc is not None:
                doc["prompt"] = masked
                masked = json.dumps(doc)
            return {V: "1.0", "http": {"transformedGatewayRequest": {"body": b64(masked)}}}
        return {V: "1.0", "http": {}}
    resp = _object(resp)
    raw = unb64(resp.get("body"))                                       # RESPONSE: the agent's answer
    blocked, masked = guard(raw, "OUTPUT")
    print(json.dumps({"point": "RESPONSE", "status": resp.get("statusCode"), "blocked": blocked, "masked": masked != raw}))
    if blocked:
        return refuse()
    if masked != raw:
        return {V: "1.0", "http": {"transformedGatewayResponse": {"body": b64(masked)}}}
    return {V: "1.0", "http": {}}
