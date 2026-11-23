"""Ask a hosted agent through the agent gateway, as a user would, and print what came back.

    demo_scenes/ask <agent> "<prompt>" [--timeout <s>] [--session <ID>]
    demo_scenes/ask <agent> --file <path> [--timeout <s>] [--session <ID>]

The call is signed with the caller's own credentials (any IAM principal that may invoke the agent gateway). It prints
`HTTP <status> (<seconds> s)` and then the answer: the `answer` field of a JSON body, the `message` or `error` field of
a refusal (a company policy, the stop and the custom guardrail answer 403 with one of them), else the body as it is.
Every account ID in it is masked. Exit 0 for a 2xx answer, 1 for any other answer or no answer, 2 for bad usage.
"""
import json
import sys
import time
from pathlib import Path

from platform_team.agent_catalog.application_form import name_problems
from platform_team.agent_gateway.gateway_targets import gateway_url
from platform_team.agent_stop.stop_agent import SESSION_HEADER
from platform_team.hosting_review.agent_cleanup import cause
from platform_team.shared_code.aws_helpers import Clients, mask, signed_post
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import load

USAGE = ('usage: demo_scenes/ask <agent> "<prompt>" [--timeout <s>] [--session <ID>]\n'
         "       demo_scenes/ask <agent> --file <path> [--timeout <s>] [--session <ID>]")
DEFAULT_TIMEOUT = 180       # s, how long the caller waits for the answer


def ask(c, s: Settings, p, agent: str, prompt: str, session: str | None = None,
        timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, float]:
    """One call of the agent through the agent gateway. Returns (HTTP status, body, seconds). A network error or a
    timeout is raised. `c` is not needed today."""
    headers = {SESSION_HEADER: session} if session else None
    t0 = time.monotonic()
    kwargs = {"timeout": timeout, **({"headers": headers} if headers else {})}
    status, body = signed_post(gateway_url(s, p, agent), {"prompt": prompt}, s.region, **kwargs)
    return status, body, time.monotonic() - t0


def answer_text(body: str) -> str:
    """The words of an answer: the `answer` of a JSON body, else its `message` or `error` (a refusal), else the body."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if isinstance(data, dict):
        for key in ("answer", "message", "error"):
            if key in data:
                value = data[key]
                return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return body


def _parse(argv: list[str]) -> dict | None:
    """{"agent", "prompt" or "file", "timeout", "session"} for the usage above, or None."""
    if not argv:
        return None
    out: dict = {"agent": argv[0], "timeout": DEFAULT_TIMEOUT, "session": None}
    rest, words = argv[1:], []
    while rest:
        arg = rest.pop(0)
        if arg in ("--file", "--timeout", "--session"):
            if not rest:
                return None
            value = rest.pop(0)
            if arg == "--timeout":
                if not (value.isdigit() and int(value) > 0):
                    return None
                value = int(value)
            out[arg[2:]] = value
        elif arg.startswith("--"):
            return None
        else:
            words.append(arg)
    if ("file" in out) == bool(words) or len(words) > 1:        # a prompt or a file, one of them
        return None
    if words:
        out["prompt"] = words[0]
    return out


def main(argv: list[str]) -> int:
    args = _parse(argv)
    if args is None:
        print(USAGE)
        return 2
    problems = name_problems(args["agent"])
    if problems:
        print(f"agent name {args['agent']!r}: {'; '.join(problems)}")
        return 2
    if "file" in args:
        try:
            args["prompt"] = Path(args["file"]).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as e:
            print(f"cannot read the prompt file {args['file']}: {type(e).__name__}")
            return 2
    if not args["prompt"].strip():
        print(USAGE)
        return 2
    account = ""
    try:
        s = Settings.from_env()
        c = Clients.for_settings(s)
        p = load(s, c)
        account = p.account
        try:
            status, body, took = ask(c, s, p, args["agent"], args["prompt"], args["session"], args["timeout"])
        except OSError as e:
            print(mask(f"no answer from {args['agent']} within {args['timeout']} s ({type(e).__name__})", account))
            return 1
    except Exception as e:          # one line, no traceback (a traceback could print the account ID)
        print(f"ask of {args['agent']} did not finish: {cause(e)}")
        return 1
    print(mask(f"HTTP {status} ({took:.1f} s)\n{answer_text(body)}", account))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
