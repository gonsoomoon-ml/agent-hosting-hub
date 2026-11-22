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
    return f.is_file() and not f.name.startswith(".") and (f.suffix == ".py" or f.name == "requirements.txt")


def _files(folder: Path) -> dict[str, Path]:
    return {f.name: f for f in sorted(folder.iterdir()) if _is_submitted(f)}


def bundle(agent_dir: Path, variant: str | None = None) -> bytes:
    """The zip to submit: the .py files and requirements.txt at the top of the folder. Nothing else goes in
    (not agent.json, notes, hidden files, subfolders). With a variant, its files replace those of the folder."""
    agent_dir = Path(agent_dir)
    files = _files(agent_dir)
    if variant:
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


def publish(agent_dir: Path, s: Settings, variant: str | None = None, c: Clients | None = None) -> dict:
    """Upload the code, write the application to the catalog and ask for approval.
    Returns record_id, status (the record's status after the request), code_key and code_version."""
    agent_dir = Path(agent_dir)
    form = agent_dir / "agent.json"
    if not form.is_file():
        raise ValueError(f"missing: {form}")
    app = json.loads(form.read_text(encoding="utf-8"))
    problems = validate(app, _catalog_tools())
    if problems:
        raise ValueError("; ".join(problems))
    code = bundle(agent_dir, variant)
    c = c or Clients.for_settings(s)
    p = load(s, c)
    if not (p.bucket and p.registry_id):
        raise RuntimeError("the hub has no submission bucket or catalog yet: run `make deploy` first")
    key = f"submissions/{app['team']}/{app['name']}/agent.zip"
    version = c.s3.put_object(Bucket=p.bucket, Key=key, Body=code)["VersionId"]
    description = app.get("description") or f"{app['name']}: agent of team {app['team']}"
    record_id = put_record(c, p.registry_id, app["name"], "AGENT", description,
                           {**app, "code_key": key, "code_version": version})
    submit(c, p.registry_id, record_id)
    status = records(c, p.registry_id)[app["name"]]["status"]
    return {"record_id": record_id, "status": status, "code_key": key, "code_version": version}


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print("usage: python -m platform_team.agent_catalog.publish_agent <agent_dir> [variant]")
        return 2
    try:
        out = publish(Path(argv[0]), Settings.from_env(), argv[1] if len(argv) == 2 else None)
    except (ValueError, RuntimeError) as e:
        print(f"not published: {e}")
        return 1
    print(f"published {out['code_key']} (version {out['code_version']}); record {out['record_id']} is {out['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
