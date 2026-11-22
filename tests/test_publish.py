import io
import json
import pathlib
import zipfile

import pytest

from platform_team.agent_catalog import publish_agent
from platform_team.agent_catalog.application_form import validate
from platform_team.agent_catalog.publish_agent import bundle
from platform_team.hosting_review import submission_check
from platform_team.shared_code.config import Settings
from tests.fakes import PLATFORM, TOOLS, FakeClients

TEMPLATE = pathlib.Path("dev_team/agent_template")


def test_bundle_takes_code_and_requirements_only(tmp_path):
    for name, text in {"main.py": "m", "agent.py": "a", "requirements.txt": "boto3\n", "agent.json": "{}", "notes.md": "x", ".env": "SECRET=1"}.items():
        (tmp_path / name).write_text(text)
    names = sorted(zipfile.ZipFile(io.BytesIO(bundle(tmp_path))).namelist())
    assert names == ["agent.py", "main.py", "requirements.txt"]


def test_variant_overlays_the_requirements(tmp_path):
    (tmp_path / "main.py").write_text("m"); (tmp_path / "requirements.txt").write_text("boto3\n")
    (tmp_path / "variants" / "v1-vulnerable").mkdir(parents=True)
    (tmp_path / "variants" / "v1-vulnerable" / "requirements.txt").write_text("boto3\njinja2==2.11.2\n")
    z = zipfile.ZipFile(io.BytesIO(bundle(tmp_path, "v1-vulnerable")))
    assert "jinja2==2.11.2" in z.read("requirements.txt").decode()


def test_template_bundle_passes_the_scan_rules(tmp_path):
    folder = tmp_path / "team_agent"
    folder.mkdir()
    for f in TEMPLATE.iterdir():
        if f.is_file():
            (folder / f.name).write_bytes(f.read_bytes())
    (folder / "agent.py").write_text("def run(prompt):\n    return prompt, []\n")
    out = tmp_path / "unpacked"
    (tmp_path / "agent.zip").write_bytes(bundle(folder))
    submission_check.unpack(tmp_path / "agent.zip", out)
    assert submission_check.check_layout(out) == []
    assert submission_check.check_requirements(out) == []
    assert sorted(p.name for p in out.iterdir()) == ["agent.py", "hub_tools.py", "main.py", "requirements.txt"]


def test_bundle_leaves_out_everything_that_is_not_code(tmp_path):
    files = {"main.py": "m", "requirements.txt": "boto3\n", ".hidden.py": "h", "data.json": "{}", "Dockerfile": "x",
             "variants/v1/main.py": "v", "__pycache__/main.cpython-313.pyc": "c", "__pycache__/x.py": "p",
             "sub/helper.py": "s", ".git/hooks.py": "g"}
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    names = sorted(zipfile.ZipFile(io.BytesIO(bundle(tmp_path))).namelist())
    assert names == ["main.py", "requirements.txt"]


def test_a_variant_that_does_not_exist_is_refused(tmp_path):
    (tmp_path / "main.py").write_text("m")
    with pytest.raises(ValueError, match="variant 'v9' not found"):
        bundle(tmp_path, "v9")


class _S3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)
        return {"VersionId": "ver-1"}


def _agent_folder(tmp_path, **changes):
    folder = tmp_path / "team_agent"
    folder.mkdir()
    (folder / "main.py").write_text("m")
    (folder / "agent.py").write_text("a")
    (folder / "requirements.txt").write_text("boto3==1.44.9\n")
    app = {"name": "quality_agent", "team": "appliance", "framework": "plain", "tools": [TOOLS[0]], **changes}
    (folder / "agent.json").write_text(json.dumps(app))
    return folder


def test_publish_uploads_records_and_submits(tmp_path, monkeypatch):
    fake = FakeClients()
    fake.s3 = _S3()
    calls = {}
    monkeypatch.setattr(publish_agent, "load", lambda s, c=None: PLATFORM)
    monkeypatch.setattr(publish_agent, "put_record",
                        lambda c, reg, name, kind, desc, payload: calls.update(put=(reg, name, kind, desc, payload)) or "rec-9")
    monkeypatch.setattr(publish_agent, "submit", lambda c, reg, rid: calls.update(submit=(reg, rid)) or "PENDING_APPROVAL")
    monkeypatch.setattr(publish_agent, "records", lambda c, reg: {"quality_agent": {"recordId": "rec-9", "status": "PENDING_APPROVAL"}})
    out = publish_agent.publish(_agent_folder(tmp_path), Settings(), c=fake)
    put, = fake.s3.puts
    assert put["Bucket"] == PLATFORM.bucket and put["Key"] == "submissions/appliance/quality_agent/agent.zip"
    assert zipfile.ZipFile(io.BytesIO(put["Body"])).namelist() == ["agent.py", "main.py", "requirements.txt"]
    reg, name, kind, _, payload = calls["put"]
    assert (reg, name, kind) == ("reg-1", "quality_agent", "AGENT")
    assert payload["code_key"] == put["Key"] and payload["code_version"] == "ver-1"
    assert calls["submit"] == ("reg-1", "rec-9")
    assert out == {"record_id": "rec-9", "status": "PENDING_APPROVAL", "code_key": put["Key"], "code_version": "ver-1"}


def test_publish_refuses_a_bad_application_before_uploading(tmp_path, monkeypatch):
    fake = FakeClients()
    fake.s3 = _S3()
    monkeypatch.setattr(publish_agent, "load", lambda s, c=None: PLATFORM)
    with pytest.raises(ValueError, match="name must match"):
        publish_agent.publish(_agent_folder(tmp_path, name="Bad Name"), Settings(), c=fake)
    assert fake.s3.puts == []


def test_template_application_passes_the_form_check():
    app = json.loads((TEMPLATE / "agent.json").read_text())
    assert validate(app, publish_agent._catalog_tools()) == []


def test_template_has_no_import_from_the_platform_package():
    for name in ("main.py", "hub_tools.py"):
        assert "platform_team" not in (TEMPLATE / name).read_text()
