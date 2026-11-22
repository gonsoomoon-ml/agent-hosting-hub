import pathlib, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOWED = {"111122223333", "123456789012"}
SKIP_DIRS = {".venv", ".terraform", "build", "node_modules", ".git", "__pycache__"}

def test_no_account_values_in_repo():
    bad = []
    for f in ROOT.rglob("*"):
        if f.is_file() and f.suffix in {".py", ".md", ".json", ".yml", ".yaml", ".sh", ".toml", ".cedar", ".txt", ".html"} and not SKIP_DIRS & set(f.relative_to(ROOT).parts):
            for m in re.findall(r"(?<![0-9])[0-9]{12}(?![0-9])", f.read_text(errors="ignore")):
                if m not in ALLOWED:
                    bad.append((str(f.relative_to(ROOT)), m))
            if re.search(r"AKIA(?!IOSFODNN7EXAMPLE)[0-9A-Z]{16}", f.read_text(errors="ignore")):
                bad.append((str(f.relative_to(ROOT)), "access key"))
    assert bad == []
