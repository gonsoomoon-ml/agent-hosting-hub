"""The hub screen's app: the FastAPI object, the shared page context, the panels and the job route.

    python -m platform_team.hub_ui        # make ui: http://127.0.0.1:8300

Every screen module (home.py, ...) has an APIRouter named `router`, builds its view from panels (`panel`: one read
through the cache; a failing read becomes one masked line in its panel, not a failed page) and answers with `page`.
create_app includes the routers of SCREENS. A POST route never checks the host, the origin or the token itself: the
Guard middleware (safety.py) has done it before the route runs, and a refused request never reaches it.

A POST route never renders a page: it answers `back(request, "/<its GET page>", msg=<key>)` for a success or
`back(..., err=<key>)` for a refusal (a bad or missing form value, an unknown name), a 303 to a GET page that shows
the sentence texts.py has for msg.<key> (class msg) or err.<key> (class err). A second press while a job runs raises
jobs.Busy in hub.jobs.start; the app answers it the same way (err=busy) on the page the button was pressed on.
"""
import importlib
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

import jinja2
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from platform_team.agent_catalog import catalog_records
from platform_team.hosting_review.agent_cleanup import cause
from platform_team.hub_ui import safety
from platform_team.hub_ui.jobs import Busy, Jobs
from platform_team.hub_ui.reads import Cache
from platform_team.hub_ui.texts import LANG_COOKIE, THEME_COOKIE, lang_of, theme_of, translator
from platform_team.hub_ui.timefmt import DEFAULT_ZONE, fmt_ts
from platform_team.shared_code import hub_state
from platform_team.shared_code.aws_helpers import _SERVICES, Clients, mask
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import NotDeployed, Platform

DEFAULT_PORT = 8300
DEFAULT_LANG = "ko"
# the modules under platform_team/hub_ui whose `router` the app includes
SCREENS = ("home", "reviews", "policies", "agents")
HERE = Path(__file__).parent
COOKIE_SECONDS = 60 * 60 * 24 * 365
# The pill color of a state AWS or a job gives (base.html: .pill.ok, .pending, .draft, .bad); another state is grey.
PILLS = {
    "ok": ("APPROVED", "READY", "ACTIVE", "OK", "SUCCEEDED", "done"),
    "pending": ("PENDING_APPROVAL", "LOG_ONLY", "INSUFFICIENT_DATA", "CREATING", "UPDATING", "RUNNING", "running"),
    "draft": ("DRAFT",),
    "bad": ("REJECTED", "ALARM", "FAILED", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED", "UPDATE_UNSUCCESSFUL",
            "DELETING", "TIMED_OUT", "ABORTED", "failed"),
}


def pill(state: Any) -> str:
    """The pill class of a state ("" for a state of no color)."""
    return next((cls for cls, states in PILLS.items() if state in states), "")


class Hub:
    """What the routes share: the settings, the AWS clients, the platform values, the cache, the values kept for good,
    the jobs, the page token and the script nonce (both new at every start). The platform values are read once, at
    the first page that needs them (a hub that is not deployed is asked again at the next page). `kept` holds what
    never changes once AWS has it (an execution's input, a finished execution's history) while the app runs; a job
    does not clear it."""

    def __init__(self, s: Settings, c, platform: Platform | None, *, port: int, cache_seconds: float, lang: str,
                 zone: str):
        self.s, self.c, self.port, self.lang, self.zone = s, c, port, lang, zone
        self._platform = platform
        self._lock = threading.Lock()
        self.cache = Cache(cache_seconds)
        self.kept: dict[str, Any] = {}
        self.jobs = Jobs(on_end=self.cache.clear)
        self.token = safety.new_token()
        self.nonce = safety.new_nonce()

    def platform(self) -> Platform:
        """The platform values (SSM /<prefix>/platform/). NotDeployed when there are none."""
        with self._lock:
            if self._platform is None:
                self._platform = hub_state.load(self.s, self.c)
            return self._platform

    def mask(self, text: str) -> str:
        """The account ID masked (aws_helpers.mask); before the platform values are read, every 12-digit number."""
        account = self._platform.account if self._platform is not None else ""
        return mask(text, account) if account else safety.mask_unknown(text)


def panel(hub: Hub, key: str, load: Callable[[], Any]) -> dict:
    """One read for one panel, through the cache: {"ok": True, "value": ...} or {"ok": False, "error": one masked
    line}. NotDeployed is not a panel's failure: it goes up to the page that says the hub is not deployed."""
    try:
        return {"ok": True, "value": hub.cache.get(key, load)}
    except NotDeployed:
        raise
    except Exception as e:              # one failing read is its panel's line, not the page's failure
        return {"ok": False, "error": hub.mask(cause(e))}


def catalog(hub: Hub) -> dict[str, dict]:
    """The catalog's records by name (AWS Agent Registry, ListRegistryRecords), through the cache."""
    return hub.cache.get("catalog", lambda: catalog_records.records(hub.c, hub.platform().registry_id))


def count(records: dict[str, dict], record_type: str, status: str) -> int:
    return sum(1 for r in records.values() if r.get("recordType") == record_type and r.get("status") == status)


def nav_counts(hub: Hub) -> dict:
    """The menu's badges: reviews = the agents whose record is PENDING_APPROVAL (None when the read failed)."""
    reviews = panel(hub, "nav.reviews", lambda: count(catalog(hub), "AGENT", "PENDING_APPROVAL"))
    return {"reviews": reviews["value"] if reviews["ok"] else None}


def _render(request: Request, template: str, *, nav: dict, status_code: int = 200, **context) -> Response:
    hub: Hub = request.app.state.hub
    lang, theme = lang_of(request, hub.lang), theme_of(request)
    t = translator(lang)
    msg, err = (request.query_params.get(name, "") for name in ("msg", "err"))
    context.update(t=t, lang=lang, theme=theme, path=request.url.path, token=hub.token, nonce=hub.nonce,
                   job=hub.jobs.current(), nav=nav, region=hub.s.region, prefix=hub.s.prefix, now=datetime.now(UTC),
                   msg=msg if t.has(f"msg.{msg}") else "", err=err if t.has(f"err.{err}") else "",
                   live=request.method == "GET")
    response = request.app.state.templates.TemplateResponse(request, template, context, status_code=status_code)
    if request.query_params.get("lang") == lang:
        response.set_cookie(LANG_COOKIE, lang, max_age=COOKIE_SECONDS, samesite="strict")
    if request.query_params.get("theme") == theme:
        response.set_cookie(THEME_COOKIE, theme, max_age=COOKIE_SECONDS, samesite="strict")
    return response


def page(request: Request, template: str, *, status_code: int = 200, **context) -> Response:
    """Render a screen's template with the shared context: t (the texts), lang, theme, path, token (the page token
    for forms), nonce (for a <script> tag), job (the running job, else the last one), nav (the menu's badges), region,
    prefix, now, msg and err (the keys of ?msg= and ?err= that texts has as msg.<key> and err.<key>; base.html shows
    their sentences), live (a GET page: the page script redraws it). A POST route answers with `back`, not a page."""
    return _render(request, template, nav=nav_counts(request.app.state.hub), status_code=status_code, **context)


def back(request: Request, to: str, *, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    """The answer of a POST route: 303 to the GET page `to` (a path of this screen, with its query if any) with
    msg=<key> (a success) or err=<key> (a refusal) for the page to show. A msg or err `to` holds already is dropped.
    `to` always stays on this screen: its leading slashes become one."""
    path, _, query = to.partition("?")
    pairs = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k not in ("msg", "err")]
    pairs += [(k, v) for k, v in (("msg", msg), ("err", err)) if v]
    return RedirectResponse("/" + path.lstrip("/\\") + (f"?{urlencode(pairs)}" if pairs else ""), status_code=303)


def _pressed_on(request: Request) -> str:
    """The page a button was pressed on: the Referer's path and query when it is a page of this screen; else /."""
    parts = urlsplit(request.headers.get("referer") or "")
    if not safety.same_origin(f"{parts.scheme}://{parts.netloc}", request.app.state.hub.port) \
            or parts.path == request.url.path:          # never back to the POST route itself
        return "/"
    return parts.path + (f"?{parts.query}" if parts.query else "")


def create_app(s: Settings, c=None, platform: Platform | None = None, *, port: int = DEFAULT_PORT,
               cache_seconds: float = 5.0, lang: str = DEFAULT_LANG, zone: str = DEFAULT_ZONE) -> FastAPI:
    """The app. Without `c` it makes the AWS clients (no call yet); with `c` and `platform` it never calls boto3.
    `port` is the one the Host and Origin checks accept; `lang` is the language without a choice (HUB_UI_LANG);
    `zone` is the zone of every time shown (HUB_UI_TZ). The screens are imported here: they import page and panel
    from this module."""
    if c is None:
        c = Clients.for_settings(s)
        for name in _SERVICES:      # every client now (no AWS call), so no two threads make one from the session later
            getattr(c, name)
    hub = Hub(s, c, platform, port=port, cache_seconds=cache_seconds, lang=lang, zone=zone)
    app = FastAPI(title="AI Agent Hosting Hub", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.hub = hub
    # autoescape=True: every template escapes, whatever its file name (Starlette's own default goes by the suffix)
    templates = Jinja2Templates(env=jinja2.Environment(loader=jinja2.FileSystemLoader(HERE / "templates"),
                                                       autoescape=True))
    templates.env.globals.update(ts=lambda value: fmt_ts(value, zone), pill=pill)
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.add_middleware(safety.MaskBodies, mask=hub.mask)
    app.add_middleware(safety.Guard, port=port, token=hub.token, lang=lang, nonce=hub.nonce)    # added last: runs first

    @app.exception_handler(NotDeployed)
    def not_deployed(request: Request, exc: NotDeployed) -> Response:
        return _render(request, "not_deployed.html", nav={}, ssm_path=s.ssm("platform") + "/")

    def unreadable(request: Request, exc: Exception) -> Response:
        return _render(request, "error.html", nav={}, status_code=502, error=hub.mask(cause(exc)))
    app.add_exception_handler(ClientError, unreadable)
    app.add_exception_handler(BotoCoreError, unreadable)

    @app.exception_handler(Busy)
    def busy(request: Request, exc: Busy) -> Response:
        return back(request, _pressed_on(request), err="busy")

    @app.exception_handler(StarletteHTTPException)
    async def not_found(request: Request, exc: StarletteHTTPException) -> Response:
        """An unknown path gets a page of the screen; /jobs/<id> (read by the page script) and other codes keep
        FastAPI's JSON answer."""
        if exc.status_code != 404 or request.url.path.startswith("/jobs/"):
            return await http_exception_handler(request, exc)
        return _render(request, "not_found.html", nav={}, status_code=404)

    @app.get("/jobs/{job_id}")
    def job_state(job_id: str) -> dict:
        """A job for the page script: its state, its lines and its error (masked like every body)."""
        job = hub.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404)
        return {"id": job.id, "kind": job.kind, "target": job.target, "state": job.state, "lines": list(job.lines),
                "error": job.error}

    for name in SCREENS:
        app.include_router(importlib.import_module(f"platform_team.hub_ui.{name}").router)
    return app
