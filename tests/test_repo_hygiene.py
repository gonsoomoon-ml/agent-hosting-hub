import fnmatch, pathlib, re, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOWED = {"111122223333", "123456789012"}
SKIP_DIRS = {".venv", ".terraform", "build", "node_modules", ".git", "__pycache__"}
HASHES = {"uv.lock", ".terraform.lock.hcl"}                 # package and provider hashes, long digit runs by nature
IGNORED = ("*.tfstate*", "*.log", ".env")                   # as .gitignore: local files that never get published


def repo_files() -> list[pathlib.Path]:
    """Every file git would publish from the repo: tracked, or new and not ignored. Without git (a copied tree),
    every file outside SKIP_DIRS that .gitignore's local files do not match."""
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, check=True).stdout.decode()
        files = [ROOT / p for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = [f for f in ROOT.rglob("*") if not SKIP_DIRS & set(f.relative_to(ROOT).parts)
                 and not any(fnmatch.fnmatch(f.name, g) for g in IGNORED)]
    return sorted(f for f in files if f.is_file())


def test_no_account_values_in_repo():
    """final review I-5: every text file, whatever its suffix (Terraform, templates, Makefile, NOTICE, ...)."""
    files = [f for f in repo_files() if f.name not in HASHES]
    assert {"Makefile", "main.tf", "review_machine.asl.json.tftpl", "agentcore.json.tmpl", ".env.example"} <= {
        f.name for f in files}
    bad = []
    for f in files:
        data = f.read_bytes()
        if b"\0" in data:                                   # not a text file
            continue
        text = data.decode(errors="ignore")
        for m in re.findall(r"(?<![0-9])[0-9]{12}(?![0-9])", text):
            if m not in ALLOWED:
                bad.append((str(f.relative_to(ROOT)), m))
        if re.search(r"AKIA(?!IOSFODNN7EXAMPLE)[0-9A-Z]{16}", text):
            bad.append((str(f.relative_to(ROOT)), "access key"))
    assert bad == []


def test_the_local_files_the_scan_skips_are_the_ones_git_ignores():
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert all(g in ignored for g in IGNORED)
