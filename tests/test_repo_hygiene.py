import fnmatch, pathlib, re, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOWED = {"123456789012", "234567890123"}                  # stand-ins for "this account" and "another account"
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
    assert {"Makefile", "main.tf", "review_machine.asl.json.tftpl", "buildspec_deploy.yml", ".env.example"} <= {
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
        if re.search(r"AKIA[0-9A-Z]{16}", text):            # no key-shaped string, not even a documented example:
            bad.append((str(f.relative_to(ROOT)), "access key"))   # a secret scan of this repo needs no exception
    assert bad == []


def test_the_one_key_shaped_value_is_put_together_where_it_is_used():
    """The review's test call sends the AWS documentation's example access key and expects the guardrail to refuse it.
    That value must have the shape of a key at run time, so Terraform joins it from two parts."""
    tf = (ROOT / "platform_team/hosting_review/terraform/main.tf").read_text()
    parts = re.search(r'EXAMPLE_KEY\s*=\s*join\("", \["([A-Z]+)", "([0-9A-Z]+)"\]\)', tf)
    assert parts, "EXAMPLE_KEY is not joined from two parts"
    value = "".join(parts.groups())
    assert re.fullmatch(r"AKIA[0-9A-Z]{16}", value) and value.endswith("EXAMPLE")


def test_the_local_files_the_scan_skips_are_the_ones_git_ignores():
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert all(g in ignored for g in IGNORED)
