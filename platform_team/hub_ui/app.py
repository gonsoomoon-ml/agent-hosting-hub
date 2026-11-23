"""The hub screen's app: the FastAPI object, the shared page context, the panels and the job route.

    python -m platform_team.hub_ui        # make ui: http://127.0.0.1:8300

Every screen module (home.py, ...) has an APIRouter named `router`, builds its view from panels (`panel`: one read
through the cache; a failing read becomes one masked line in its panel, not a failed page) and answers with `page`.
create_app includes the routers of SCREENS. A POST route never checks the host, the origin or the token itself: the
Guard middleware (safety.py) has done it before the route runs, and a refused request never reaches it.
"""
import importlib
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from platform_team.agent_catalog import catalog_records
from platform_team.hosting_review.agent_cleanup import cause
from platform_team.hub_ui import safety
from platform_team.hub_ui.jobs import Busy, Jobs
from platform_team.hub_ui.reads import Cache
from platform_team.hub_ui.texts import LANG_COOKIE, THEME_COOKIE, lang_of, theme_of, translator
from platform_team.hub_ui.timefmt import DEFAULT_ZONE, fmt_ts
from platform_team.shared_code import hub_state
from platform_team.shared_code.aws_helpers import Clients, mask
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import NotDeployed, Platform

DEFAULT_PORT = 8300
DEFAULT_LANG = "ko"
SCREENS = ("home",)                     # the modules under platform_team/hub_ui whose `router` the app includes
HERE = Path(__file__).parent
COOKIE_SECONDS = 60 * 60 * 24 * 365
# The pill color of a state AWS or a job gives (base.html: .pill.ok, .pending, .draft, .bad); another state is grey.
PILLS = {
    "ok": ("APPROVED", "READY", "ACTIVE", "OK", "done"),
    "pending": ("PENDING_APPROVAL", "LOG_ONLY", "INSUFFICIENT_DATA", "CREATING", "UPDATING", "running"),
    "draft": ("DRAFT",),
    "bad": ("REJECTED", "ALARM", "FAILED", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED", "UPDATE_UNSUCCESSFUL",
            "DELETING", "failed"),
}


def pill(state: Any) -> str:
    """The pill class of a state ("" for a state of no color)."""
    return next((cls for cls, states in PILLS.items() if state in states), "")


class Hub:
    """What the routes share: the settings, the AWS clients, the platform values, the cache, the jobs, the page
    token. The platform values are read once, at the first page that needs them (a hub that is not deployed is
    asked again at the next page)."""

    def __init__(self, s: Settings, c, platform: Platform | None, *, port: int, cache_seconds: float, lang: str,
                 zone: str):
        self.s, self.c, self.port, self.lang, self.zone = s, c, port, lang, zone
        self._platform = platform
        self._lock = threading.Lock()
        self.cache = Cache(cache_seconds)
        self.jobs = Jobs(on_end=self.cache.clear)
        self.token = safety.new_token()

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
    msg = request.query_params.get("msg", "")
    context.update(t=t, lang=lang, theme=theme, path=request.url.path, token=hub.token, job=hub.jobs.current(),
                   nav=nav, region=hub.s.region, prefix=hub.s.prefix, now=datetime.now(UTC),
                   msg=msg if t.has(f"msg.{msg}") else "", live=request.method == "GET")
    response = request.app.state.templates.TemplateResponse(request, template, context, status_code=status_code)
    if request.query_params.get("lang") == lang:
        response.set_cookie(LANG_COOKIE, lang, max_age=COOKIE_SECONDS, samesite="strict")
    if request.query_params.get("theme") == theme:
        response.set_cookie(THEME_COOKIE, theme, max_age=COOKIE_SECONDS, samesite="strict")
    return response


def page(request: Request, template: str, *, status_code: int = 200, **context) -> Response:
    """Render a screen's template with the shared context: t (the texts), lang, theme, path, token (the page token
    for forms), job (the running job, else the last one), nav (the menu's badges), region, prefix, now, msg (a
    message key from ?msg=, shown when texts has msg.<key>), live (a GET page: the page script redraws it)."""
    return _render(request, template, nav=nav_counts(request.app.state.hub), status_code=status_code, **context)


def _back(request: Request) -> str:
    """The page the button was pressed on: the Referer's path and query when it is this screen's own (without msg),
    else /."""
    parts = urlsplit(request.headers.get("referer") or "")
    if not safety.same_origin(f"{parts.scheme}://{parts.netloc}", request.app.state.hub.port):
        return "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "msg"])
    return "/" + parts.path.lstrip("/") + (f"?{query}" if query else "")


def create_app(s: Settings, c=None, platform: Platform | None = None, *, port: int = DEFAULT_PORT,
               cache_seconds: float = 5.0, lang: str = DEFAULT_LANG, zone: str = DEFAULT_ZONE) -> FastAPI:
    """The app. Without `c` it makes the AWS clients (no call yet); with `c` and `platform` it never calls boto3.
    `port` is the one the Host and Origin checks accept; `lang` is the language without a choice (HUB_UI_LANG);
    `zone` is the zone of every time shown (HUB_UI_TZ). The screens are imported here: they import page and panel
    from this module."""
    if c is None:
        c = Clients.for_settings(s)
        c.ssm           # the first client sets up the session's shared parts before any thread makes another
    hub = Hub(s, c, platform, port=port, cache_seconds=cache_seconds, lang=lang, zone=zone)
    app = FastAPI(title="AI Agent Hosting Hub", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.hub = hub
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.globals.update(ts=lambda value: fmt_ts(value, zone), pill=pill)
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.add_middleware(safety.MaskBodies, mask=hub.mask)
    app.add_middleware(safety.Guard, port=port, token=hub.token, lang=lang)        # added last: runs first

    @app.exception_handler(NotDeployed)
    def not_deployed(request: Request, exc: NotDeployed) -> Response:
        return _render(request, "not_deployed.html", nav={}, ssm_path=s.ssm("platform") + "/")

    def unreadable(request: Request, exc: Exception) -> Response:
        return _render(request, "error.html", nav={}, status_code=502, error=hub.mask(cause(exc)))
    app.add_exception_handler(ClientError, unreadable)
    app.add_exception_handler(BotoCoreError, unreadable)

    @app.exception_handler(Busy)
    def busy(request: Request, exc: Busy) -> Response:
        back = _back(request)
        return RedirectResponse(f"{back}{'&' if '?' in back else '?'}msg=busy", status_code=303)

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
