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
