"""Start the hub screen on this PC: python -m platform_team.hub_ui (make ui).

    HUB_UI_PORT   the port (default 8300); the screen listens on 127.0.0.1 only, whatever is set
    HUB_UI_LANG   the language of a page without a choice: ko (default) or en
    HUB_UI_TZ     the zone of the times shown (default Asia/Seoul)

The Region and the prefix come from AWS_REGION and DEMO_PREFIX as for every command of the hub (make ui reads .env
too). The credentials are the shell's: every read and every button runs with them.
"""
import os

import uvicorn

from platform_team.hub_ui.app import DEFAULT_LANG, DEFAULT_PORT, create_app
from platform_team.hub_ui.timefmt import DEFAULT_ZONE
from platform_team.shared_code.config import Settings

HOST = "127.0.0.1"          # fixed: the screen has no login, so it is never reachable from another machine


def main() -> None:
    s = Settings.from_env()
    port = int(os.environ.get("HUB_UI_PORT") or DEFAULT_PORT)
    app = create_app(s, port=port, lang=os.environ.get("HUB_UI_LANG") or DEFAULT_LANG,
                     zone=os.environ.get("HUB_UI_TZ") or DEFAULT_ZONE)
    print(f"hub screen (prefix {s.prefix}, region {s.region}): http://{HOST}:{port}   (Ctrl+C stops it)", flush=True)
    uvicorn.run(app, host=HOST, port=port, log_level="warning", access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
