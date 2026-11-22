import io, urllib.error, urllib.request
from botocore.credentials import Credentials
from botocore.exceptions import ClientError
from platform_team.shared_code.aws_helpers import mask, already_exists, wait_status, signed_post
import pytest

CREDS = Credentials("test-access-key", "test-secret-key")                  # stand-ins: the request is signed, never sent
URL = "https://gateway.invalid/mcp"                                                    # never reached: urlopen is patched

class Answer(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *exc): self.close()

def test_signed_post_signs_the_request_and_returns_status_and_text(monkeypatch):
    sent = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: sent.append(req) or Answer(b'{"ok": true}\n'))
    assert signed_post(URL, {"a": 1}, "us-west-2", creds=CREDS) == (200, '{"ok": true}')
    req = sent[0]
    assert (req.get_method(), req.full_url, req.data) == ("POST", URL, b'{"a": 1}')
    assert req.get_header("Authorization").startswith("AWS4-HMAC-SHA256")

def test_signed_post_returns_an_http_error_status_instead_of_raising(monkeypatch):
    def refuse(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"error": "denied"}'))
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert signed_post(URL, {}, "us-west-2", creds=CREDS) == (403, '{"error": "denied"}')

def test_mask_hides_the_account():
    assert mask("arn:aws:iam::123456789012:role/x", "123456789012") == "arn:aws:iam::<ACCOUNT>:role/x"

def test_already_exists_reads_code_and_message():
    err = lambda code, msg: ClientError({"Error": {"Code": code, "Message": msg}}, "Op")
    assert already_exists(err("ConflictException", "x")) and already_exists(err("ValidationException", "name already exists"))
    assert not already_exists(err("AccessDeniedException", "no"))

def test_wait_status_raises_on_failed_state():
    with pytest.raises(RuntimeError, match="CREATE_FAILED"):
        wait_status(lambda: {"status": "CREATE_FAILED", "statusReasons": ["why"]}, ("READY",), "thing", timeout=1, step=0)
