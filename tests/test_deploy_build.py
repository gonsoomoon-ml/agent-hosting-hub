import re, zipfile
from pathlib import Path

import pytest, yaml
from botocore.exceptions import ClientError

from platform_team.hosting_review import deploy_build as d
from platform_team.hosting_review.deploy_build import deploy, install_command, package, runtime_config
from tests.fakes import FakeClients

ROLE = "arn:aws:iam::123456789012:role/hub-agent-quality_agent-role"
GW = "https://hub-tools-abcdefghij.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp"
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
ENV = {"AGENT": "quality_agent", "PREFIX": "hub", "AWS_REGION": "us-west-2", "ROLE_ARN": ROLE, "TOOL_GW_URL": GW,
       "MODEL_ID": MODEL, "BUCKET": "hub-123456789012-us-west-2", "CODE_KEY": "submissions/quality_agent/agent.zip",
       "CODE_VERSION": "v1"}
BUILDSPEC = Path(d.__file__).with_name("buildspec_deploy.yml")


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Fake time: sleeping moves the clock, nothing waits."""
    now = {"t": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: now["t"])
    monkeypatch.setattr("time.sleep", lambda seconds: now.update(t=now["t"] + seconds))
    return now


def _files(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


# ------------------------------------------------------------------ what is installed, and how

def test_dependencies_come_as_wheels_for_the_runtimes_platform():
    assert install_command(Path("r.txt"), Path("site")) == [
        "uv", "pip", "install", "--quiet", "--no-compile", "--only-binary", ":all:", "--python-platform", "aarch64-manylinux2014",
        "--python-version", "3.13", "--target", "site", "-r", "r.txt"]

def test_the_platforms_requirements_list_what_requirements_txt_lists():
    req = 'boto3==1.40.0  # the SDK\n\n# a comment\nrequests[socks]>=2\nurllib3 \\\n  <3\n'
    assert d.requirements_from(req) == "boto3==1.40.0\nrequests[socks]>=2\nurllib3 <3\n"

def test_the_platforms_requirements_follow_the_scan_rule():
    for line in ("--index-url https://example.com/simple", "pkg @ https://example.com/pkg.whl", "./local_pkg",
                 'jinja2==2.11.2 ; platform_release == ""', "-r other.txt"):
        with pytest.raises(ValueError, match=r"^requirements\.txt: .+: " + re.escape(line) + "$"):
            d.requirements_from(f"requests\n{line}\n")

def test_the_submissions_build_settings_are_deleted(tmp_path):
    _files(tmp_path, {"main.py": "team code", "requirements.txt": "boto3\n", "helpers/util.py": "X = 1\n",
                      "pyproject.toml": "[project]\nname = 'team'\n", "uv.lock": "version = 1\n",
                      "uv.toml": "[pip]\nindex-url = 'http://127.0.0.1:9/evil-simple'\n", ".python-version": "3.8\n"})
    assert d.drop_build_settings(tmp_path) == [".python-version", "pyproject.toml", "uv.lock", "uv.toml"]
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "helpers/util.py", "main.py", "requirements.txt"]
    assert d.drop_build_settings(tmp_path) == []

def test_the_deploy_build_reads_no_uv_config_and_installs_no_node_or_cli():
    doc = yaml.safe_load(BUILDSPEC.read_text())
    assert doc["env"]["variables"] == {"UV_NO_CONFIG": "1"}
    assert doc["phases"]["install"]["runtime-versions"] == {"python": 3.13}
    commands = [c for phase in doc["phases"].values() for c in phase.get("commands", [])]
    assert all(isinstance(c, str) for c in commands)
    assert not [c for c in commands if re.search(r"\b(npm|node|agentcore|cdk)\b", c)]


# ------------------------------------------------------------------ the package

def test_the_package_holds_the_dependencies_and_the_submitted_python_files_only(tmp_path):
    """site/strands/__init__.py and src/main.py, src/agent.py go in; src/notes.txt, src/sub/x.py and any __pycache__ do not."""
    site, src, out = tmp_path / "site", tmp_path / "src", tmp_path / "package.zip"
    _files(site, {"strands/__init__.py": "S = 1\n", "strands/__pycache__/x.cpython-313.pyc": "",
                  "strands-1.0.dist-info/METADATA": "Name: strands\n"})
    _files(src, {"main.py": "M = 1\n", "agent.py": "A = 1\n", "notes.txt": "n\n", "sub/x.py": "X = 1\n",
                 "__pycache__/main.cpython-313.pyc": "", "requirements.txt": "strands-agents\n"})
    size = package(src, site, out)
    assert size == out.stat().st_size > 0
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == ["agent.py", "main.py", "strands-1.0.dist-info/METADATA", "strands/__init__.py"]
        assert z.read("main.py") == b"M = 1\n"

def test_the_package_is_the_same_for_the_same_files(tmp_path):
    site, src = tmp_path / "site", tmp_path / "src"
    _files(site, {"b/x.py": "1", "a/y.py": "2"})
    _files(src, {"main.py": "m"})
    package(src, site, tmp_path / "one.zip")
    package(src, site, tmp_path / "two.zip")
    assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()


# ------------------------------------------------------------------ the Runtime

def test_the_runtime_gets_the_agents_role_and_the_hubs_four_variables():
    cfg = runtime_config(ENV, "packages/quality_agent/v1.zip")
    assert cfg["roleArn"] == ENV["ROLE_ARN"] and sorted(cfg["environmentVariables"]) == ["AGENT_NAME", "HUB_REGION", "MODEL_ID", "TOOL_GATEWAY_URL"]
    assert cfg["agentRuntimeArtifact"]["codeConfiguration"]["entryPoint"] == ["opentelemetry-instrument", "main.py"]
    assert cfg == {
        "agentRuntimeArtifact": {"codeConfiguration": {
            "code": {"s3": {"bucket": "hub-123456789012-us-west-2", "prefix": "packages/quality_agent/v1.zip"}},
            "runtime": "PYTHON_3_13", "entryPoint": ["opentelemetry-instrument", "main.py"]}},
        "roleArn": ROLE, "networkConfiguration": {"networkMode": "PUBLIC"}, "protocolConfiguration": {"serverProtocol": "HTTP"},
        "environmentVariables": {"HUB_REGION": "us-west-2", "TOOL_GATEWAY_URL": GW, "MODEL_ID": MODEL, "AGENT_NAME": "quality_agent"},
        "description": "hosted agent"}

ADOT = "aws-opentelemetry-distro==0.24.0"       # PyPI's latest on 2026-11-22


def test_the_runtime_is_started_with_tracing_on():
    # The AWS guide's direct code deployment for Python: entryPoint ["opentelemetry-instrument", "main.py"], with the
    # ADOT package (aws-opentelemetry-distro) in the code package. The service model takes at most two items.
    import botocore.session
    entry = runtime_config(ENV, "packages/quality_agent/v1.zip")["agentRuntimeArtifact"]["codeConfiguration"]["entryPoint"]
    assert entry == ["opentelemetry-instrument", "main.py"]
    model = botocore.session.get_session().get_service_model("bedrock-agentcore-control")
    shape = model.operation_model("CreateAgentRuntime").input_shape.members["agentRuntimeArtifact"]
    entry_shape = shape.members["codeConfiguration"].members["entryPoint"]
    assert len(entry) <= entry_shape.metadata["max"] == 2
    # the package comes from requirements.txt: the template and every agent folder hold the pin (a variant only adds lines)
    dev = Path(d.__file__).resolve().parents[2] / "dev_team"
    for req in [dev / "agent_template" / "requirements.txt", *sorted(dev.glob("*/requirements.txt")),
                *sorted(dev.glob("preloaded_agents/*/requirements.txt")),
                *sorted(dev.glob("*/variants/*/requirements.txt"))]:
        assert ADOT in req.read_text().splitlines(), req

def test_a_first_deploy_creates_the_runtime_and_a_later_one_updates_it():
    c = FakeClients()
    first = deploy(c, ENV, "packages/quality_agent/v1.zip"); second = deploy(c, ENV, "packages/quality_agent/v2.zip")
    assert (first["created"], second["created"]) == (True, False) and first["runtimeArn"] == second["runtimeArn"]
    assert c.parameters["/hub/agents/quality_agent/runtime_arn"] == first["runtimeArn"]
    assert (first["version"], second["version"]) == ("1", "2") and first["runtimeId"] == "hub_quality_agent-Ab12Cd34Ef"
    assert c.runtime_calls == ["create hub_quality_agent", "update hub_quality_agent-Ab12Cd34Ef"]
    code = c.runtimes["hub_quality_agent"]["config"]["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]
    assert code["prefix"] == "packages/quality_agent/v2.zip"

def test_a_runtime_of_another_name_is_not_updated():
    c = FakeClients()
    c.ctl.create_agent_runtime(agentRuntimeName="hub_quality", **runtime_config({**ENV, "AGENT": "quality"}, "k"))
    assert deploy(c, ENV, "packages/quality_agent/v1.zip")["created"] is True
    assert sorted(c.runtimes) == ["hub_quality", "hub_quality_agent"]

def test_a_runtime_on_a_later_page_is_found():
    c = FakeClients()
    deploy(c, ENV, "packages/quality_agent/v1.zip")
    listed = c.ctl.list_agent_runtimes()["agentRuntimes"]
    pages = {None: {"agentRuntimes": [{**listed[0], "agentRuntimeName": f"other_{i}"} for i in range(100)], "nextToken": "p2"},
             "p2": {"agentRuntimes": listed}}
    c.ctl.list_agent_runtimes = lambda **kw: pages[kw.get("nextToken")]
    assert deploy(c, ENV, "packages/quality_agent/v2.zip")["created"] is False

def test_deploy_fails_with_the_reason_when_the_runtime_does_not_become_ready():
    c = FakeClients(runtime_status="CREATE_FAILED", runtime_failure="the code package could not be read")
    with pytest.raises(RuntimeError, match="Runtime hub_quality_agent CREATE_FAILED: the code package could not be read"):
        deploy(c, ENV, "packages/quality_agent/v1.zip")
    assert "/hub/agents/quality_agent/runtime_arn" not in c.parameters

def test_deploy_waits_until_the_new_version_is_ready(clock):
    c = FakeClients(runtime_ready_after=3)
    out = deploy(c, ENV, "packages/quality_agent/v1.zip")
    assert out["version"] == "1" and c.runtime_gets == 4                 # three looks at CREATING, then READY
    assert out["readySeconds"] == 3 * d.READY_STEP == clock["t"] - 1000.0

def test_a_runtime_still_not_ready_after_the_wait_stops_the_deploy():
    c = FakeClients(runtime_ready_after=float("inf"))
    with pytest.raises(TimeoutError, match="Runtime hub_quality_agent not .* within 30s"):
        deploy(c, ENV, "packages/quality_agent/v1.zip", wait=30)
    assert "/hub/agents/quality_agent/runtime_arn" not in c.parameters


def _error(code, message):
    return ClientError({"Error": {"Code": code, "Message": message}}, "CreateAgentRuntime")

def test_create_is_tried_again_while_the_new_execution_role_settles():
    c = FakeClients()
    c.runtime_create_errors = [_error("ValidationException", "Role validation failed for the execution role"),
                               _error("AccessDeniedException", "The service cannot assume the role")]
    assert deploy(c, ENV, "packages/quality_agent/v1.zip")["created"] is True
    assert c.runtime_create_tries == 3

def test_create_is_not_tried_again_when_this_steps_own_role_lacks_a_permission():
    c = FakeClients()
    own = ("User: arn:aws:sts::123456789012:assumed-role/hub-review-deploy-role/x is not authorized to perform: "
           "bedrock-agentcore:CreateAgentRuntime on resource: arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/*")
    c.runtime_create_errors = [_error("AccessDeniedException", own)]
    with pytest.raises(ClientError, match="is not authorized to perform: bedrock-agentcore:CreateAgentRuntime"):
        deploy(c, ENV, "packages/quality_agent/v1.zip")
    assert c.runtime_create_tries == 1

def test_create_is_not_tried_again_when_this_steps_own_role_cannot_pass_the_execution_role():
    c = FakeClients()
    own = ("User: arn:aws:sts::123456789012:assumed-role/hub-review-deploy-role/x is not authorized to perform: "
           "iam:PassRole on resource: arn:aws:iam::123456789012:role/hub-agent-quality_agent-role")
    c.runtime_create_errors = [_error("AccessDeniedException", own)]
    with pytest.raises(ClientError, match="is not authorized to perform: iam:PassRole"):
        deploy(c, ENV, "packages/quality_agent/v1.zip")
    assert c.runtime_create_tries == 1

def test_create_stops_after_eight_tries():
    c = FakeClients()
    c.runtime_create_errors = [_error("ValidationException", "Role validation failed")] * 9
    with pytest.raises(ClientError, match="Role validation failed"):
        deploy(c, ENV, "packages/quality_agent/v1.zip")
    assert c.runtime_create_tries == 8

def test_any_other_create_error_is_not_tried_again():
    c = FakeClients()
    c.runtime_create_errors = [_error("ServiceQuotaExceededException", "too many Runtimes")]
    with pytest.raises(ClientError, match="too many Runtimes"):
        deploy(c, ENV, "packages/quality_agent/v1.zip")
    assert c.runtime_create_tries == 1
