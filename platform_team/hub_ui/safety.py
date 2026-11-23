"""The safety rules of a local screen that can change AWS. The screen has no login: it listens on 127.0.0.1, and
these rules keep a web page of another site from using it through the presenter's browser.

- Every request must name this PC as its host (127.0.0.1:<port> or localhost:<port>). A page of another site that
  makes its own name point at 127.0.0.1 (DNS rebinding) still sends its own name, and is refused.
- A request that can change something (any method but GET and HEAD) must come from this screen's own page (Origin)
  and carry the page token (the form field `token`), which only this screen's pages hold. The token is new at every
  start of the app.
- No page of another site may show this screen inside its own (a frame), where a click on the page would be a
  click on this screen's button: every answer says so (X-Frame-Options, Content-Security-Policy frame-ancestors).
  The same policy runs only the scripts that carry this start's nonce (the page's own two) and loads styles and
  pictures from this app only, so markup that slipped into a page could not run a script.
- Every HTML and JSON body leaves the app with the account ID masked (aws_helpers.mask).

A refused request never reaches a route: no AWS call is made and no job starts.
"""
import hmac
import html
import re
import secrets
from typing import Callable
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from platform_team.hub_ui.texts import lang_of, translator

SAFE_METHODS = ("GET", "HEAD")
FORM = "application/x-www-form-urlencoded"
ACCOUNT_ID = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")       # any 12-digit number, when the account is not known yet
MASKED = "<ACCOUNT>"                                             # what aws_helpers.mask writes for the account ID


def _here(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def allowed_host(host: str | None, port: int) -> bool:
    """The Host header names this PC and this app's port: 127.0.0.1:<port> or localhost:<port>."""
    return isinstance(host, str) and host.lower() in _here(port)


def same_origin(origin: str | None, port: int) -> bool:
    """The Origin header is this screen's own: http://127.0.0.1:<port> or http://localhost:<port>. No Origin is not."""
    return isinstance(origin, str) and origin.lower() in {f"http://{h}" for h in _here(port)}


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_nonce() -> str:
    """The nonce of the page scripts for one start of the app (base64url, as a CSP nonce may be)."""
    return secrets.token_urlsafe(18)


def headers(nonce: str) -> list[tuple[bytes, bytes]]:
    """What every answer carries: no frame on another site, scripts with this nonce only, nothing from elsewhere, and
    forms sent to this app only (default-src does not cover form-action)."""
    policy = (f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
              "img-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'")
    return [(b"x-frame-options", b"DENY"), (b"content-security-policy", policy.encode()),
            (b"x-content-type-options", b"nosniff")]


def token_ok(sent: str | None, token: str) -> bool:
    """The token a form sent is the page token (compared in constant time)."""
    return isinstance(sent, str) and hmac.compare_digest(sent.encode(), token.encode())


def mask_unknown(text: str) -> str:
    """Mask every 12-digit number: used while the account ID is not known (the platform values are not read yet)."""
    return ACCOUNT_ID.sub(MASKED, text)


def _form_token(content_type: str | None, body: bytes) -> str | None:
    """The one value of the field `token` in an HTML form body; None for another body or none or several values."""
    if not (content_type or "").lower().startswith(FORM):
        return None
    values = parse_qs(body.decode("utf-8", "replace")).get("token", [])
    return values[0] if len(values) == 1 else None


async def _read_body(receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return body
        body += message.get("body", b"")
        if not message.get("more_body"):
            return body


def _replay(body: bytes, receive):
    """A receive that gives the route the body the guard read, then whatever comes next (a disconnect)."""
    given = False

    async def replay():
        nonlocal given
        if not given:
            given = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()
    return replay


def _with_headers(send, extra: list[tuple[bytes, bytes]]):
    async def send_with_headers(message):
        if message["type"] == "http.response.start":
            message = {**message, "headers": [*message.get("headers", []), *extra]}
        await send(message)
    return send_with_headers


class Guard:
    """ASGI middleware: the host check for every request, then the origin and token checks for a request that can
    change something. A refused request gets 403 and one sentence in the language of the page. Every answer gets
    headers(nonce)."""

    def __init__(self, app, port: int, token: str, lang: str, nonce: str):
        self.app, self.port, self.token, self.lang = app, port, token, lang
        self.headers = headers(nonce)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":            # the screen has none: the handshake is refused
            return await send({"type": "websocket.close", "code": 1008})
        if scope["type"] != "http":                 # lifespan
            return await self.app(scope, receive, send)
        send = _with_headers(send, self.headers)
        request = Request(scope)
        refused = None
        if not allowed_host(request.headers.get("host"), self.port):
            refused = "refused.host"
        elif scope["method"] not in SAFE_METHODS:
            if not same_origin(request.headers.get("origin"), self.port):
                refused = "refused.origin"
            else:
                body = await _read_body(receive)
                if token_ok(_form_token(request.headers.get("content-type"), body), self.token):
                    receive = _replay(body, receive)
                else:
                    refused = "refused.token"
        if refused:
            t = translator(lang_of(request, self.lang))
            return await PlainTextResponse(t(refused, port=self.port), status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)


def _content_type(headers) -> bytes:
    return next((v for k, v in headers if k.lower() == b"content-type"), b"").lower()


class MaskBodies:
    """ASGI middleware: every text and JSON body leaves the app through `mask` (the account ID becomes <ACCOUNT>).
    In HTML the mark is written as &lt;ACCOUNT&gt;, so the browser shows it instead of reading it as a tag.
    Other bodies (the pictures) go out as they are."""

    def __init__(self, app, mask: Callable[[str], str]):
        self.app, self.mask = app, mask

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "HEAD":
            return await self.app(scope, receive, send)
        start, chunks = None, []

        async def masked(message):
            nonlocal start
            if message["type"] == "http.response.start" and _content_type(message.get("headers", [])).startswith(
                    (b"text/", b"application/json")):
                start = message
                return
            if message["type"] == "http.response.body" and start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                text = self.mask(b"".join(chunks).decode("utf-8", "surrogateescape"))
                if _content_type(start.get("headers", [])).startswith(b"text/html"):
                    text = text.replace(MASKED, html.escape(MASKED))
                body = text.encode("utf-8", "surrogateescape")
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                await send({**start, "headers": headers + [(b"content-length", str(len(body)).encode())]})
                return await send({"type": "http.response.body", "body": body, "more_body": False})
            return await send(message)
        return await self.app(scope, receive, masked)
