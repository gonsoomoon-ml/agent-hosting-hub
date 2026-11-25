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
    """Every text file, whatever its suffix (Terraform, templates, Makefile, NOTICE, ...)."""
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
        # no key-shaped string (a long-term AKIA or a temporary ASIA key ID), not even a documented example: a secret
        # scan of this repo needs no exception
        if re.search(r"(AKIA|ASIA)[0-9A-Z]{16}", text):
            bad.append((str(f.relative_to(ROOT)), "access key"))
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


# ---------------------------------------------------------------- what a reader of this repo can open
def _text_files() -> list[pathlib.Path]:
    out = []
    for f in repo_files():
        if f.name in HASHES or f.suffix in {".png", ".tar", ".zip", ".webm", ".mp4"}:
            continue
        data = f.read_bytes()
        if b"\0" not in data:
            out.append(f)
    return out


def test_every_picture_a_readme_names_is_in_the_repo():
    """A README that names a picture (as a link, an image or a path in code ticks) names one that is in the repo. The
    top-level READMEs show the concept picture; the page on the structure shows both pictures."""
    named = re.compile(r"[\w./-]+\.(?:png|jpg|jpeg|svg|gif)\b")
    missing = []
    for md in (f for f in repo_files() if f.suffix == ".md"):
        for name in named.findall(md.read_text(encoding="utf-8")):
            if name.startswith("http"):
                continue
            if not ((md.parent / name).exists() or (ROOT / name).exists()):
                missing.append((str(md.relative_to(ROOT)), name))
    assert missing == []
    for readme in ("README.md", "README.en.md"):
        assert "](docs/hosting-hub-concept.png)" in (ROOT / readme).read_text(encoding="utf-8")
    page = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    for picture in ("hosting-hub-concept.png", "hosting-hub-system.png"):
        assert f"]({picture})" in page, f"docs/architecture.md does not show {picture}"
        assert (ROOT / "docs" / picture).stat().st_size > 10_000


def test_every_concept_picture_sentence_points_at_the_picture_in_the_repo():
    """A feature README's section on the concept picture links the picture itself."""
    sections = []
    for md in (ROOT / "platform_team").glob("*/README.md"):
        text = md.read_text(encoding="utf-8")
        if "## 개념도에서의 위치" in text:
            body = text.split("## 개념도에서의 위치", 1)[1].split("\n## ", 1)[0]
            sections.append((md, body))
    assert len(sections) >= 10
    for md, body in sections:
        assert "hosting-hub-concept.png" in body, f"{md.relative_to(ROOT)} does not link the concept picture"
        target = re.search(r"\]\(([^)]*hosting-hub-concept\.png)\)", body)
        assert target and (md.parent / target.group(1)).resolve() == ROOT / "docs/hosting-hub-concept.png"


# what points outside the repo: a task or plan number, a design section sign, the earlier experiments' checks/ folder,
# a scene or take by number, a "(picture N)" that names no file
OUTSIDE = [r"§", r"\b[Tt]ask[ -]?\d", r"\b[Pp]lan[ -]\d", r"(?<![\w/.-])checks/", r"\b(?:scene|take) ?\d", r"장면 ?\d+번",
           r"\(pictures? [0-9①-⑫]", r"picture step"]


def test_no_tracked_file_points_outside_the_repo():
    me = pathlib.Path(__file__).resolve()
    bad = []
    for f in _text_files():
        if f.resolve() == me or ".superpowers" in f.parts:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for pattern in OUTSIDE:
                if re.search(pattern, line):
                    bad.append((f"{f.relative_to(ROOT)}:{n}", pattern))
    assert bad == []


def test_notice_has_no_empty_form_and_names_every_source():
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Fill in" not in notice and "<" not in notice, "NOTICE still holds a form's instruction or a blank"
    entries = [e for e in re.split(r"\n(?=- Source repository:)", notice) if e.startswith("- Source repository:")]
    assert entries
    for e in entries:
        for field in ("Path:", "Commit:", "License:", "Used in:"):
            assert field in e, f"an entry of NOTICE has no {field}"
    used = " ".join(" ".join(e.split("Used in:", 1)[1].split()) for e in entries)
    sources = []
    for f in _text_files():
        head = "\n".join(f.read_text(encoding="utf-8", errors="ignore").splitlines()[:5])
        if f.name != "NOTICE" and re.search(r"\b(?:Adapted|Copied) from https?://", head):
            sources.append(str(f.relative_to(ROOT)))
    assert sources, "no file names its source in a first comment"
    assert [s for s in sources if s not in used] == []


# the three scene commands (ask, search, logs) and publish name demo_scenes in their usage lines, and the files that
# make them run say so in a comment; nothing else of the hub's code names the video's folders
SCENE_COMMAND_FILES = {"platform_team/agent_gateway/ask_agent.py", "platform_team/agent_catalog/search_catalog.py",
                       "platform_team/agent_monitoring/agent_logs.py", "platform_team/shared_code/hub_env.sh",
                       "platform_team/dev_access/terraform/main.tf"}
VIDEO_TESTS = {"tests/test_demo_scenes.py", "tests/test_demo_video.py", "tests/test_repo_hygiene.py"}


def test_the_hub_does_not_depend_on_the_video_folder():
    """make deploy, make e2e, make test (apart from the video's own two test files) and the Lambda package never read
    demo_video/ or demo_scenes/."""
    makefile = [ln for ln in (ROOT / "Makefile").read_text().splitlines() if not ln.lstrip().startswith("#")]
    assert [ln for ln in makefile if re.search(r"demo_video|demo_scenes", ln)] == []
    from platform_team.shared_code.code_package import _hub_files
    assert not [n for n in _hub_files() if re.search(r"demo_", n)]
    video = re.compile(r"demo_video|demo_scenes")
    users = set()
    for f in _text_files():
        rel = str(f.relative_to(ROOT))
        if rel.startswith(("platform_team/", "dev_team/", "e2e_checks/", "tests/")) and not rel.endswith(".md") \
                and video.search(f.read_text(encoding="utf-8", errors="ignore")):
            users.add(rel)
    assert users - SCENE_COMMAND_FILES - VIDEO_TESTS == set()
    for rel in SCENE_COMMAND_FILES:        # in those, a comment or a usage line names a scene command, nothing else
        code = [ln for ln in (ROOT / rel).read_text().splitlines()
                if video.search(re.sub(r"demo_scenes/(?:ask|publish|search|logs)\b", "", ln))
                and not ln.lstrip().startswith("#")]
        assert code == [], (rel, code)


def test_the_spikes_are_records_that_no_command_runs():
    """e2e_checks/spikes/ says what each experiment tried and when; no file outside the folder runs or imports one
    (the READMEs may name them)."""
    readme = (ROOT / "e2e_checks/spikes/README.md").read_text(encoding="utf-8")
    for name in ("spike_cli_in_codebuild.py", "spike_terraform/", "spike_operations.py"):
        assert name in readme
    assert "2026-11-22" in readme and "돌리지 않습니다" in readme
    users = [str(f.relative_to(ROOT)) for f in _text_files()
             if "e2e_checks/spikes/" not in str(f) and f.suffix != ".md" and f.name != "test_repo_hygiene.py"
             and re.search(r"spike_(?:cli_in_codebuild|terraform|operations)", f.read_text(encoding="utf-8", errors="ignore"))]
    assert users == []


# ---------------------------------------------------------------- the top-level READMEs and the pages under docs/
READMES = ("README.md", "README.en.md")
PAGES = ("getting-started.md", "commands.md", "checks.md", "cost-and-cleanup.md", "limits.md", "architecture.md",
         "demo-guide.md")


def _tree_folders(text: str) -> set[str]:
    """The folders the README's tree names, as paths from the repo root (the tree is two levels deep)."""
    block = text.split("```text\n", 1)[1].split("```", 1)[0]
    out, parent = set(), ""
    for line in block.splitlines():
        m = re.match(r"^(│   )?[├└]── (\S+)/(?:\s|$)", line)
        if not m:
            continue
        if m.group(1):
            out.add(f"{parent}/{m.group(2)}")
        else:
            parent = m.group(2)
            out.add(parent)
    return out


def test_the_readmes_folder_tree_is_the_repos():
    """Every folder in the tree is in the repo, every folder of the two teams is in the tree, and both languages
    draw the same tree."""
    trees = {name: _tree_folders((ROOT / name).read_text(encoding="utf-8")) for name in READMES}
    assert trees["README.md"] == trees["README.en.md"]
    tree = trees["README.md"]
    assert len(tree) > 20
    assert [p for p in sorted(tree) if not (ROOT / p).is_dir()] == []
    tracked = {f.relative_to(ROOT).parts for f in repo_files()}
    for team in ("platform_team", "dev_team"):
        folders = {f"{team}/{parts[1]}" for parts in tracked if parts[0] == team and len(parts) > 2}
        assert folders - tree == set(), f"the README's tree leaves out folders of {team}/"


def test_the_code_the_walk_through_names_is_there():
    """Every file, function and Terraform resource named in the walk through the code (docs/architecture.md) exists."""
    body = (ROOT / "docs/architecture.md").read_text(encoding="utf-8").split("## 코드 따라 읽기", 1)[1]
    ticks = set(re.findall(r"`([^`]+)`", body))
    files = {t for t in ticks if "/" in t and "<" not in t}
    functions = {t[:-2] for t in ticks if t.endswith("()")}
    resources = {t for t in ticks if re.fullmatch(r"aws_\w+\.\w+", t)}
    assert len(files) >= 6 and len(functions) >= 6 and resources
    assert [f for f in sorted(files) if not (ROOT / f).is_file()] == []
    code = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in sorted(files))
    assert [f for f in sorted(functions) if not re.search(rf"^def {re.escape(f)}\(", code, re.M)] == []
    for kind, label in (r.split(".") for r in resources):
        assert f'resource "{kind}" "{label}"' in code


def test_the_readme_is_short_and_the_two_languages_have_the_same_sections():
    """The top-level README is the way in; what is long lives in the pages under docs/."""
    korean = (ROOT / "README.md").read_text(encoding="utf-8")
    assert korean.count("\n") <= 150 and len(korean) <= 8000
    counts = {name: len(re.findall(r"^## ", (ROOT / name).read_text(encoding="utf-8"), re.M)) for name in READMES}
    assert counts["README.md"] == counts["README.en.md"] >= 4


def test_the_readmes_link_every_page_under_docs():
    pages = sorted(f.name for f in (ROOT / "docs").glob("*.md"))
    assert pages == sorted(PAGES)
    for readme in READMES:
        text = (ROOT / readme).read_text(encoding="utf-8")
        assert [p for p in pages if f"](docs/{p})" not in text] == [], f"{readme} does not link every page under docs/"


def _anchor(heading: str) -> str:
    """A heading's anchor as GitHub makes it: code ticks and punctuation dropped, blanks to hyphens, lower case."""
    text = re.sub(r"[^\w\- ]", "", heading.replace("`", "")).strip().lower()
    return text.replace(" ", "-")


def test_every_link_in_the_readmes_and_the_pages_leads_to_a_file_and_a_heading():
    """A relative link in a top-level README or in a page under docs/ leads to a file of the repo and, where it names
    one, to a heading of that file."""
    sources = [ROOT / name for name in READMES] + [ROOT / "docs" / name for name in PAGES]
    seen = 0
    for source in sources:
        for target, anchor in re.findall(r"\]\(([^)#\s]*)(?:#([^)\s]+))?\)", source.read_text(encoding="utf-8")):
            if target.startswith("http"):
                continue
            file = (source.parent / target).resolve() if target else source
            where = f"{source.relative_to(ROOT)} links {target}#{anchor or ''}"
            assert file.exists(), f"{where}, which is not in the repo"
            if anchor:
                headings = re.findall(r"^#+ (.+)$", file.read_text(encoding="utf-8"), re.M)
                assert anchor in {_anchor(h) for h in headings}, f"{where}, a heading the file does not have"
            seen += 1
    assert seen >= 60


# ---------------------------------------------------------------- the demo video's address
VIDEO = "https://youtu.be/cp0YKgAmrxM"


def test_the_documents_link_one_video():
    """The narrated demo video is on YouTube under one address. Every YouTube link in the documents is that address,
    both top-level READMEs carry it in their first lines and on the poster, and the page on the video's build carries
    it. A video that is uploaded anew gets a new address, and then every place has to follow."""
    links = {}
    for md in (f for f in repo_files() if f.suffix == ".md"):
        found = re.findall(r"https?://(?:www\.)?(?:youtu\.be|youtube\.com)/[^\s)>\]]+", md.read_text(encoding="utf-8"))
        if found:
            links[str(md.relative_to(ROOT))] = set(found)
    assert set().union(*links.values()) == {VIDEO}
    assert {"README.md", "README.en.md", "demo_video/README.md"} <= set(links)
    for readme in ("README.md", "README.en.md"):
        text = (ROOT / readme).read_text(encoding="utf-8")
        assert VIDEO in "\n".join(text.splitlines()[:5]), f"{readme} does not link the video in its first lines"
        assert f"](demo_video/poster.png)]({VIDEO})" in text, f"{readme}: the poster does not lead to the video"
