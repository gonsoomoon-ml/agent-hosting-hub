# tests/test_submission.py
import zipfile, pytest
from platform_team.hosting_review.submission_check import unpack, check_layout

def make(tmp_path, files):
    z = tmp_path / "s.zip"
    with zipfile.ZipFile(z, "w") as f:
        for name, text in files.items():
            f.writestr(name, text)
    return z

def test_bad_submission_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unsafe path in the submission: ../evil.py"):
        unpack(make(tmp_path, {"../evil.py": "x"}), tmp_path / "out")
    unpack(make(tmp_path, {"agent.py": "x"}), tmp_path / "out2")
    assert check_layout(tmp_path / "out2") == ["missing: main.py", "missing: requirements.txt"]


# every kind of unsafe name _unsafe handles, not only ../
import stat

@pytest.mark.parametrize("name", ["../evil.py", "app/../../evil.py", "/etc/evil.py", "C:\\evil.py", "C:/evil.py",
                                  "c:evil.py", "..\\evil.py", "app\\..\\..\\evil.py", "\\\\server\\share\\evil.py",
                                  "\\evil.py"])
def test_every_unsafe_name_is_refused_before_anything_is_written(tmp_path, name):
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="unsafe path in the submission"):
        unpack(make(tmp_path, {"main.py": "x", name: "x"}), out)
    assert not out.exists()

def test_a_symbolic_link_is_refused_before_anything_is_written(tmp_path):
    z = tmp_path / "s.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("main.py", "x")
        link = zipfile.ZipInfo("requirements.txt")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        f.writestr(link, "/etc/passwd")
    with pytest.raises(ValueError, match="unsafe path in the submission: requirements.txt"):
        unpack(z, tmp_path / "out")
    assert not (tmp_path / "out").exists()

def test_a_name_that_only_looks_odd_is_kept(tmp_path):
    unpack(make(tmp_path, {"main.py": "x", "requirements.txt": "boto3\n", "notes..py": "x", "app/x.py": "x"}), tmp_path / "out")
    assert (tmp_path / "out" / "notes..py").is_file() and (tmp_path / "out" / "app" / "x.py").is_file()

def test_good_submission_unpacks(tmp_path):
    unpack(make(tmp_path, {"main.py": "x", "requirements.txt": "boto3\n"}), tmp_path / "out")
    assert check_layout(tmp_path / "out") == []


# One rule for requirements.txt, used by the scan and the deploy: packages by name (and version) from the index only.
import re, yaml
from pathlib import Path
from platform_team.hosting_review import submission_check
from platform_team.hosting_review.submission_check import check_requirements

SCAN = Path(__file__).resolve().parents[1] / "platform_team" / "hosting_review" / "buildspec_scan.yml"

def buildspec_commands(path):
    doc = yaml.safe_load(path.read_text())
    commands = [c for phase in doc["phases"].values() for c in phase.get("commands", [])]
    assert all(isinstance(c, str) for c in commands), commands     # an unquoted ": " turns a command into a mapping
    return commands

def requirements(tmp_path, text):
    (tmp_path / "requirements.txt").write_text(text)
    return check_requirements(tmp_path)

def test_requirements_by_name_and_version_pass(tmp_path):
    text = 'boto3==1.44.9  # the SDK\n\n# a note\nrequests[socks] >=2, <3\nurllib3 \\\n  <3\n'
    assert requirements(tmp_path, text) == []

def test_requirements_that_pick_their_own_source_are_refused(tmp_path):
    for line in ("--index-url https://example.com/simple", "-r more.txt", "-e .", "boto3==1.44.9 --hash=sha256:abc",
                 "pkg @ https://example.com/pkg-1.0-py3-none-any.whl", "pkg@file:///tmp/pkg.whl",
                 "https://example.com/pkg-1.0.tar.gz", "./local_pkg", "file:../pkg"):
        problems = requirements(tmp_path, f"requests\n{line}\n")
        assert len(problems) == 1 and problems[0].startswith("requirements.txt: ") and problems[0].endswith(line), line

def test_requirements_with_an_environment_marker_are_refused(tmp_path):
    # The scan's pip and the deploy's uv test a marker against different machines, so a marked line can be
    # skipped by the audit and installed by the deploy. The target is fixed (Linux aarch64, CPython 3.13).
    for line in ('jinja2==2.11.2 ; platform_release == ""', 'jinja2==2.11.2;platform_machine=="aarch64"',
                 'requests>=2 ; python_version >= "3.10"'):
        problems = requirements(tmp_path, f"boto3\n{line}\n")
        assert problems == [f"requirements.txt: environment markers are not allowed (the Runtime is Linux aarch64, "
                            f"CPython 3.13): {line}"], line

def test_the_command_line_refuses_bad_requirements(tmp_path, capsys):
    z = make(tmp_path, {"main.py": "x", "requirements.txt": "pkg @ https://example.com/pkg.whl\n"})
    audit = tmp_path / "audit" / "requirements.txt"
    assert submission_check.main([str(z), str(tmp_path / "out"), str(audit)]) == 1
    assert "submission refused: requirements.txt: direct references are not allowed" in capsys.readouterr().out
    assert not audit.exists()                                 # nothing to audit: the scan stops here

def test_the_scan_runs_no_python_from_the_submission_folder():
    commands = buildspec_commands(SCAN)
    [check] = [c for c in commands if "submission_check" in c]
    src, audit_file = check.split()[-2:]                      # where the submission is unpacked, and the audit file
    [audit] = [c for c in commands if "pip_audit -r" in c]
    assert src.startswith("/") and "python3 -I -m pip_audit" in audit and f"-r {audit_file} " in audit
    assert not audit_file.startswith(f"{src}/")               # the platform's file, not one of the submission
    assert not any(re.search(rf"\bcd {re.escape(src)}(/|\s|$)", c) for c in commands)   # never works inside it
    assert "PIP_ONLY_BINARY=:all: python3" in audit           # no sdist's setup.py runs, as in the deploy


# The scan audits the lines the deploy installs: both come from submission_check.requirements_from.
import io, types
from platform_team.hosting_review import deploy_build

DEPLOY = SCAN.with_name("buildspec_deploy.yml")
DEPLOY_ENV = {"AGENT": "quality_agent", "PREFIX": "hub", "AWS_REGION": "us-west-2", "MODEL_ID": "m",
              "ROLE_ARN": "arn:aws:iam::123456789012:role/hub-agent-quality_agent-role", "TOOL_GW_URL": "https://x",
              "BUCKET": "hub-123456789012-us-west-2", "CODE_KEY": "submissions/quality_agent/agent.zip",
              "CODE_VERSION": "v1"}


class _AtInstall(Exception):
    """Stops the deploy build at its install command."""


def deploy_installs(tmp_path, monkeypatch, zip_path) -> list[str]:
    """The lines of the file the deploy build hands uv (install_command's -r) for the submission at zip_path."""
    seen = {}
    def install(cmd, cwd):
        seen["lines"] = Path(cmd[cmd.index("-r") + 1]).read_text().splitlines()
        raise _AtInstall
    work = tmp_path / "deploy"
    work.mkdir()
    monkeypatch.setattr(deploy_build, "run", install)
    monkeypatch.setattr(deploy_build.tempfile, "mkdtemp", lambda prefix: str(work))
    s3 = types.SimpleNamespace(get_object=lambda **kw: {"Body": io.BytesIO(zip_path.read_bytes())})
    with pytest.raises(_AtInstall):
        deploy_build.main(DEPLOY_ENV, types.SimpleNamespace(s3=s3))
    return seen["lines"]


def test_the_scan_audits_exactly_the_lines_the_deploy_installs(tmp_path, monkeypatch):
    """For a requirements.txt with a comment ending in a backslash before `jinja2==2.11.2`, the audit file's lines
    equal the lines of the file the deploy build installs from. No line is in one and not the other."""
    text = "boto3==1.40.0\n# the template's pin \\\njinja2==2.11.2\nrequests[socks] >=2,<3  # http\n"
    z = make(tmp_path, {"main.py": "x", "requirements.txt": text})
    audit = tmp_path / "audit" / "requirements.txt"
    assert submission_check.main([str(z), str(tmp_path / "src"), str(audit)]) == 0
    audited = audit.read_text().splitlines()
    assert audited == deploy_installs(tmp_path, monkeypatch, z)
    # The continuation joins the jinja2 line to the comment for both (pip, given the team's own file, would not
    # join a comment line and would audit jinja2 that the deploy does not install).
    assert audited == ["boto3==1.40.0", "requests[socks] >=2,<3"]


def test_the_builds_install_their_tools_at_one_version():
    for path in (SCAN, DEPLOY):
        installs = [c for c in buildspec_commands(path) if "pip install" in c]
        assert installs and all(re.fullmatch(r"python3 -m pip install --quiet [a-z-]+==\d+(\.\d+)+", c) for c in installs), \
            (path.name, installs)
