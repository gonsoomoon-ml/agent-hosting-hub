"""A development team's agent goes to the hub: the code to the submission bucket, the application to the catalog,
and a request for approval, which starts the hosting review.

    python -m platform_team.agent_catalog.publish_agent <agent_dir> [variant]      # dev_team/agent_template/publish.sh

The folder holds the agent's code, requirements.txt and agent.json (the application). variant names a folder
under <agent_dir>/variants/ whose files replace the ones of the same name (a version of the agent for a demo).
"""
import io
import json
import sys
import zipfile
from pathlib import Path

from platform_team.agent_catalog.application_form import validate
from platform_team.agent_catalog.catalog_records import put_record, records, submit
from platform_team.sample_tools.tool_schema import TARGETS
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import load

_FIXED_TIME = (1980, 1, 1, 0, 0, 0)       # the same files give the same zip


def _is_submitted(f: Path) -> bool:
    return f.is_file() and not f.is_symlink() and not f.name.startswith(".") and (f.suffix == ".py" or f.name == "requirements.txt")


def _files(folder: Path) -> dict[str, Path]:
    return {f.name: f for f in sorted(folder.iterdir()) if _is_submitted(f)}


def bundle(agent_dir: Path, variant: str | None = None) -> bytes:
    """The zip to submit: the .py files and requirements.txt at the top of the folder. Nothing else goes in
    (not agent.json, notes, hidden files, subfolders). With a variant, its files replace those of the folder."""
    agent_dir = Path(agent_dir)
    files = _files(agent_dir)
    if variant:
        if variant in (".", "..") or "/" in variant or "\\" in variant:
            raise ValueError(f"variant {variant!r} must be a folder name under variants/")
        folder = agent_dir / "variants" / variant
        if not folder.is_dir():
            raise ValueError(f"variant {variant!r} not found: {folder} is not a folder")
        files |= _files(folder)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, _FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name].read_bytes())
    return buf.getvalue()


def _catalog_tools() -> set[str]:
    return {f"{target}___{t['name']}" for target, tools in TARGETS.items() for t in tools}


class PublishFailed(Exception):
    """A step failed. The message says which one, why, what already succeeded and what to do."""


def _cause(e: Exception) -> str:
    err = getattr(e, "response", {}).get("Error")
    return f"{err['Code']}: {err.get('Message', '')}" if err else f"{type(e).__name__}: {e}"


def publish(agent_dir: Path, s: Settings, variant: str | None = None, c: Clients | None = None) -> dict:
    """Upload the code, write the application to the catalog and ask for approval.
    Returns record_id, status (the record's status after the request), code_key, code_version and, when the
    request was not made, a note. Running it again is safe: the key is fixed, each run adds an object version."""
    agent_dir = Path(agent_dir)
    form = agent_dir / "agent.json"
    if not form.is_file():
        raise ValueError(f"missing: {form}")
    app = json.loads(form.read_text(encoding="utf-8"))
    problems = validate(app, _catalog_tools(), s)
    if problems:
        raise ValueError("; ".join(problems))
    code = bundle(agent_dir, variant)
    c = c or Clients.for_settings(s)
    p = load(s, c)
    if not (p.bucket and p.registry_id):
        raise RuntimeError("the hub has no submission bucket or catalog yet: run `make deploy` first")
    key = f"submissions/{app['team']}/{app['name']}/agent.zip"
    done = "nothing yet"

    def failed(step: str, e: Exception, next_step: str) -> PublishFailed:
        return PublishFailed(f"{step} failed ({_cause(e)}). Done so far: {done}. {next_step} "
                             "Running publish again is safe.")
    try:
        version = c.s3.put_object(Bucket=p.bucket, Key=key, Body=code)["VersionId"]
    except Exception as e:
        raise failed("upload", e, "Nothing was changed; run again.") from e
    done = f"code uploaded as version {version}"
    description = app.get("description") or f"{app['name']}: agent of team {app['team']}"
    try:
        record_id = put_record(c, p.registry_id, app["name"], "AGENT", description,
                               {**app, "code_key": key, "code_version": version})
        status = records(c, p.registry_id)[app["name"]]["status"]
    except Exception as e:
        raise failed("writing the record", e, "The record not written; run again.") from e
    out = {"record_id": record_id, "status": status, "code_key": key, "code_version": version}
    if status != "DRAFT":     # an update that changes nothing keeps the status; the registry refuses a second request
        out["note"] = f"record is {status}: not submitted again"
        return out
    done += f", record {record_id} written"
    try:
        submit(c, p.registry_id, record_id)
        out["status"] = records(c, p.registry_id)[app["name"]]["status"]
    except Exception as e:
        raise failed("asking for approval", e, "The record stays DRAFT; run again to ask.") from e
    return out


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print("usage: python -m platform_team.agent_catalog.publish_agent <agent_dir> [variant]")
        return 2
    hub = "this hub"            # the first line says which hub: its prefix and region
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        out = publish(Path(argv[0]), s, argv[1] if len(argv) == 2 else None)
    except (ValueError, RuntimeError, PublishFailed) as e:
        print(f"not published ({hub}): {e}")
        return 1
    except Exception as e:      # reading the hub's values, credentials: say what failed, no traceback
        print(f"not published ({hub}): {_cause(e)}")
        return 1
    print(f"published {out['code_key']} (version {out['code_version']}); record {out['record_id']} is {out['status']} "
          f"({hub})")
    if out.get("note"):
        print(out["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
