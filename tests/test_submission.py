# tests/test_submission.py  (Review Focus 4)
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
    text = 'boto3==1.44.9  # the SDK\n\n# a note\nrequests[socks] >=2, <3 ; python_version >= "3.10"\nurllib3 \\\n  <3\n'
    assert requirements(tmp_path, text) == []

def test_requirements_that_pick_their_own_source_are_refused(tmp_path):
    for line in ("--index-url https://example.com/simple", "-r more.txt", "-e .", "boto3==1.44.9 --hash=sha256:abc",
                 "pkg @ https://example.com/pkg-1.0-py3-none-any.whl", "pkg@file:///tmp/pkg.whl",
                 "https://example.com/pkg-1.0.tar.gz", "./local_pkg", "file:../pkg"):
        problems = requirements(tmp_path, f"requests\n{line}\n")
        assert len(problems) == 1 and problems[0].startswith("requirements.txt: ") and problems[0].endswith(line), line

def test_the_command_line_refuses_bad_requirements(tmp_path, capsys):
    z = make(tmp_path, {"main.py": "x", "requirements.txt": "pkg @ https://example.com/pkg.whl\n"})
    assert submission_check.main([str(z), str(tmp_path / "out")]) == 1
    assert "submission refused: requirements.txt: direct references are not allowed" in capsys.readouterr().out

def test_the_scan_runs_no_python_from_the_submission_folder():
    commands = buildspec_commands(SCAN)
    [check] = [c for c in commands if "submission_check" in c]
    src = check.split()[-1]                                   # the folder the submission is unpacked into
    [audit] = [c for c in commands if "pip_audit -r" in c]
    assert src.startswith("/") and "python3 -I -m pip_audit" in audit and f"-r {src}/requirements.txt" in audit
    assert not any(re.search(rf"\bcd {re.escape(src)}(/|\s|$)", c) for c in commands)   # never works inside it
    assert "PIP_ONLY_BINARY=:all: python3" in audit           # no sdist's setup.py runs, as in the deploy
