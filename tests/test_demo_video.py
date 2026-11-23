"""The demo video's developer PC (demo_video/tools/dev_pc): a container with Claude Code on Amazon Bedrock and the
developer role's temporary credentials. What can be checked without Docker or AWS: the outputs are git-ignored, the
settings hold no credential and allow only the listed tools, the MCP template has the documented shape, the Bedrock
session policy allows only the two invoke actions on the video's two models, and run.sh keeps its rules. With a fake
docker on PATH: once the home folder exists, run.sh writes inside it only through docker exec (a link planted from
inside the container is never followed on this PC), and it fails closed without the metadata service's blackhole."""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "demo_video"
DEV_PC = VIDEO / "tools" / "dev_pc"
SERVER = "hub-catalog"
MODELS = ("us.anthropic.claude-sonnet-5-5", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
ALLOWED = [f"mcp__{SERVER}__*", "Edit(./dev_team/**)", "Bash(search:*)", "Bash(logs:*)", "Bash(ls:*)", "Bash(cat:*)"]
# the credential files; and every file a pre-allowed command runs or reads (the scene commands, the hub's code, the
# project's Python), and Claude Code's own settings and MCP servers
DENIED = ["Read(//run/dev-pc/**)", "Edit(./demo_scenes/**)", "Edit(./platform_team/**)", "Edit(./.claude/**)",
          "Edit(./.mcp.json)", "Edit(./pyproject.toml)", "Edit(./uv.lock)",
          # under dev_team/, where edits need no question: no Claude Code folder (skills, hooks, settings), MCP server
          # list or instructions file that a later session would load
          "Edit(./dev_team/**/.claude/**)", "Edit(./dev_team/**/.mcp.json)", "Edit(./dev_team/**/CLAUDE.md)"]
SKIP_WORDS = ("--dangerously-skip-permissions", "dangerously", "--permission-mode", "bypassPermissions", "acceptEdits")


def _settings() -> dict:
    return json.loads((DEV_PC / "settings.json").read_text(encoding="utf-8"))


def test_the_video_outputs_and_the_credential_files_are_git_ignored():
    assert "out/" in (VIDEO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for path in ("demo_video/out/dev-pc/creds/developer.ini", "demo_video/out/dev-pc/creds/bedrock.json",
                 "demo_video/out/dev-pc/home/work/.mcp.json", "demo_video/out/raw/take.webm"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0, path


def test_the_settings_hold_no_credential_and_allow_only_the_listed_tools():
    s = _settings()
    assert set(s) == {"env", "awsCredentialExport", "permissions", "enabledMcpjsonServers", "disableAutoMode"}
    assert s["permissions"]["allow"] == ALLOWED and s["permissions"]["deny"] == DENIED
    # Claude Code 2.1.330 starts in auto mode unless told otherwise (it said so at its first start in the container on
    # 2026-11-23): the mode that asks before any tool the list does not allow is set here, and auto mode is switched
    # off (the settings reference's disableAutoMode, value "disable", any settings file)
    assert set(s["permissions"]) == {"defaultMode", "allow", "deny"} and s["permissions"]["defaultMode"] == "default"
    assert s["disableAutoMode"] == "disable"
    assert s["enabledMcpjsonServers"] == [SERVER]
    env = s["env"]
    assert env == {"CLAUDE_CODE_USE_BEDROCK": "1", "ANTHROPIC_MODEL": MODELS[0], "ANTHROPIC_DEFAULT_HAIKU_MODEL": MODELS[1],
                   "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1"}
    # Claude Code's own Bedrock token comes from a command that reads the file run.sh creds writes; the settings name
    # the file, never a value, and give the tools no AWS profile or key of their own
    assert s["awsCredentialExport"] == "cat /run/dev-pc/bedrock.json"
    text = (DEV_PC / "settings.json").read_text(encoding="utf-8")
    for word in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_BEARER_TOKEN",
                 "SecretAccessKey", "Bash(*)", "Bash(aws", "Bash(publish", "pytest", "Read(./**)", "Edit(./**)",
                 *SKIP_WORDS):
        assert word not in text, word
    assert not re.search(r"(AKIA|ASIA)[0-9A-Z]{16}", text)


def test_no_pre_allowed_rule_is_broader_than_the_list_or_reaches_a_denied_file():
    allow = _settings()["permissions"]["allow"]
    # each Bash rule is one command word, each Edit rule stays under dev_team/, the MCP rule names the one server
    assert sorted(re.fullmatch(r"Bash\((\w+):\*\)", a).group(1) for a in allow if a.startswith("Bash(")) == [
        "cat", "logs", "ls", "search"]
    assert [a for a in allow if a.startswith("Edit(")] == ["Edit(./dev_team/**)"]
    assert [a for a in allow if a.startswith("mcp__")] == [f"mcp__{SERVER}__*"]
    assert not [a for a in allow if a.startswith(("Read(", "Write(", "WebFetch", "WebSearch", "Agent", "Task"))]
    edits = [a[len("Edit("):-1] for a in allow if a.startswith("Edit(")]
    for path in ("./demo_scenes/search", "./demo_scenes/logs", "./platform_team/shared_code/hub_env.sh",
                 "./.claude/settings.json", "./.mcp.json", "./pyproject.toml", "./uv.lock", "./CLAUDE.md"):
        assert not [e for e in edits if fnmatchcase(path, e)], path
    assert fnmatchcase("./dev_team/quality_agent/agent.py", edits[0])


def test_no_claude_code_folder_mcp_list_or_instructions_may_be_written_under_dev_team():
    # Edit(./dev_team/**) lets Claude Code write there without a question; a nested .claude/ (a skill, a hook), a
    # .mcp.json or a CLAUDE.md there would be read by a later session, so each is denied
    deny = [d[len("Edit("):-1] for d in _settings()["permissions"]["deny"] if d.startswith("Edit(./dev_team/")]
    assert deny == ["./dev_team/**/.claude/**", "./dev_team/**/.mcp.json", "./dev_team/**/CLAUDE.md"]
    for path in ("./dev_team/x/.claude/skills/y/SKILL.md", "./dev_team/quality_agent/.claude/settings.json",
                 "./dev_team/x/.mcp.json", "./dev_team/quality_agent/CLAUDE.md"):
        assert [d for d in deny if fnmatchcase(path, d)], path
    for path in ("./dev_team/quality_agent/agent.py", "./dev_team/quality_agent/requirements.txt"):
        assert not [d for d in deny if fnmatchcase(path, d)], path


def test_the_readme_and_the_projects_claude_md_say_what_the_settings_say():
    readme = (VIDEO / "README.md").read_text(encoding="utf-8")
    for rule in ALLOWED + DENIED + ['"disableAutoMode": "disable"', '"defaultMode": "default"']:
        assert f"`{rule}`" in readme, rule
    claude_md = (DEV_PC / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`dev_team/` 아래에만" in claude_md and "개발자가 직접" in claude_md
    for folder in ("`demo_scenes/`", "`platform_team/`", "`.claude/`", "`.mcp.json`", "`pyproject.toml`", "`uv.lock`"):
        assert folder in claude_md, folder


def test_the_mcp_template_has_the_documented_shape():
    servers = json.loads((DEV_PC / "mcp.json.tmpl").read_text(encoding="utf-8"))["mcpServers"]
    assert list(servers) == [SERVER]
    server = servers[SERVER]
    assert server["command"] == "mcp-proxy-for-aws" and server.get("type", "stdio") == "stdio"
    args = server["args"]
    assert args[0] == "https://agent-registry.<REGION>.api.aws/registry/<REGISTRY_ID>/mcp"
    assert args[args.index("--service") + 1] == "agent-registry" and args[args.index("--region") + 1] == "<REGION>"
    assert "env" not in server                         # the proxy reads the container's default profile: the developer


def test_the_bedrock_token_may_only_invoke_the_two_models_of_the_video():
    raw = (DEV_PC / "bedrock-policy.json.tmpl").read_text(encoding="utf-8")
    assert "<ACCOUNT>" in raw and "<REGION>" in raw
    policy = json.loads(raw.replace("<ACCOUNT>", "123456789012").replace("<REGION>", "us-west-2"))
    [statement] = policy["Statement"]
    assert statement["Effect"] == "Allow" and set(statement) == {"Sid", "Effect", "Action", "Resource"}
    assert statement["Action"] == ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    profiles = [f"arn:aws:bedrock:us-west-2:123456789012:inference-profile/{m}" for m in MODELS]
    # what each profile routes to (list-inference-profiles, us-west-2, 2026-11-23): the same model in three Regions
    models = [f"arn:aws:bedrock:{r}::foundation-model/{m.removeprefix('us.')}" for m in MODELS
              for r in ("us-east-1", "us-east-2", "us-west-2")]
    assert sorted(statement["Resource"]) == sorted(profiles + models)
    assert [r for r in statement["Resource"] if "*" in r] == []
    s = _settings()
    assert (s["env"]["ANTHROPIC_MODEL"], s["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"]) == MODELS


def _code(path: Path) -> str:
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))


def test_run_sh_keeps_its_rules():
    run = DEV_PC / "run.sh"
    assert os.access(run, os.X_OK)
    code = _code(run)
    assert "set -x" not in code and "xtrace" not in code and "set -euo pipefail" in code
    for sub in ("build", "creds", "up", "check", "term", "agent", "stop", "forget", "down"):
        assert re.search(r"^\s*%s\)" % sub, code, re.M), sub
    assert "umask 077" in code and "chmod 700" in code
    assert "--role-session-name developer" in code and "--name hub-video-claude" in code
    assert "--duration-seconds 14400" in code                                        # the Bedrock token: 4 hours
    [ttyd] = [line for line in code.splitlines() if "ttyd -i lo" in line]
    assert re.search(r"\bttyd -i lo -p 7681 -O docker exec ", ttyd)                  # loopback only, same origin
    run_block = code.split("docker run", 1)[1].split("\n\n", 1)[0]
    assert not re.search(r"\s(-p|--publish)[\s=]", run_block)
    assert "--security-opt no-new-privileges" in run_block
    assert "AWS_EC2_METADATA_DISABLED=true" in code               # no fallback to this PC's instance credentials,
    # and no process reaches them at all: root adds the route once, by absolute path with a fixed PATH
    assert re.search(r"--user root --env PATH=/usr/sbin:/usr/bin:/sbin:/bin \"\$name\" "
                     r"/usr/bin/ip route add blackhole 169\.254\.169\.254/32", code)
    assert "git -C" in code and "check-ignore" in code            # the checkout is the tracked files; creds are ignored


def test_no_skip_mode_host_network_or_passed_through_value_anywhere():
    for f in (DEV_PC / "run.sh", DEV_PC / "Dockerfile", DEV_PC / "settings.json"):
        code = _code(f)
        for word in (*SKIP_WORDS, "--privileged", "--env-file", "docker.sock", ".aws"):
            assert word not in code, (f.name, word)
        assert not re.search(r"--net(work)?[= ]host", code), f.name
        # every --env / -e names its value: no variable of this PC passes through by name
        assert not re.search(r"(--env|\s-e)\s+[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_=])", code), f.name


def test_run_sh_refuses_bad_usage_before_anything_runs():
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")} | {"PATH": "/usr/bin:/bin"}
    usage = ("usage: demo_video/tools/dev_pc/run.sh build | creds | up | check | term | agent <name> | stop | forget"
             " | down\n")
    for args, says in (([], usage), (["nope"], usage), (["agent"], usage), (["up", "x"], usage),
                       (["agent", "../x"], "agent name '../x': not an agent name\n"),
                       (["agent", "nope"], "no agent 'nope' in the repo's dev_team/\n")):
        r = subprocess.run([str(DEV_PC / "run.sh"), *args], capture_output=True, text=True, env=env, timeout=30)
        assert (r.returncode, r.stdout, r.stderr) == (2, says, ""), args


def test_the_image_pins_its_tools_and_takes_nothing_from_this_pc():
    text = (DEV_PC / "Dockerfile").read_text(encoding="utf-8")
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", text, re.M))
    docker = re.sub(r"\$\{(\w+)\}", lambda m: args.get(m.group(1), m.group(0)), text)     # the ARGs as built
    assert args["CLAUDE_CODE_VERSION"] == "2.1.330"                                    # the version of this PC
    assert 'npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"' in text
    assert re.search(r'"mcp-proxy-for-aws==\d+\.\d+\.\d+"', docker) and "uv tool install" in docker
    assert re.search(r"^FROM node:22\.\d+\.\d+-bookworm-slim$", docker, re.M)
    # the scene commands are found last on PATH: a file in the editable checkout never shadows ls, cat, uv or ip
    assert re.search(r"PATH=\$PATH:/home/dev/work/demo_scenes$", docker, re.M) and "demo_scenes:$PATH" not in docker
    assert not re.search(r"^\s*(COPY|ADD)\s+(?!--from=)", docker, re.M)             # no file of this PC in a layer
    assert not re.search(r"ARG\s+\w*(KEY|SECRET|TOKEN|PASSWORD)", docker, re.I)
    readme = (VIDEO / "README.md").read_text(encoding="utf-8")
    version = re.search(r"mcp-proxy-for-aws==(\d+\.\d+\.\d+)", docker).group(1)
    assert f"mcp-proxy-for-aws=={version}" in readme


def test_the_container_files_name_no_person_host_or_account():
    for f in sorted(DEV_PC.iterdir()) + [VIDEO / "README.md"]:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text.replace("123456789012", "")), f.name
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text.replace("@anthropic-ai/claude-code@", "")), f.name
        assert "/home/ubuntu" not in text and "ip-172-" not in text, f.name


def test_the_projects_claude_md_tells_where_the_template_is_and_the_three_commands():
    text = (DEV_PC / "CLAUDE.md").read_text(encoding="utf-8")
    for needle in ("dev_team/agent_template", "agent.json", "requirements.txt", "`search ", "`publish ", "`logs ",
                   SERVER):
        assert needle in text, needle
    # it is what a developer of this hub writes down, not the scenes' script
    for word in ("Project Falcon", "asking again", "v2-loop", "v1-vulnerable", "incident", "사고"):
        assert word not in text, word


# ------------------------------------------------------------------ run.sh against a fake docker, in a temporary repo

FAKE_DOCKER = r'''#!PYTHON
"""A fake docker: writes nothing on disk except its own log and the standard input it was given."""
import os, sys
args = sys.argv[1:]
log = os.environ["FAKE_LOG"]
n = sum(1 for _ in open(log)) if os.path.exists(log) else 0
line = " ".join(" ".join(a.split()) for a in args)                # one call, one line
if args[:1] == ["exec"] and "-i" in args[:args.index(os.environ.get("FAKE_NAME", "hub-dev-pc"))]:
    data = sys.stdin.buffer.read()
    with open(os.path.join(os.environ["FAKE_STDIN"], f"{n}"), "wb") as f:
        f.write(data)
with open(log, "a") as f:
    f.write(line + "\n")
if args[:1] == ["run"]:
    print("cid")
if args[:1] != ["exec"]:
    sys.exit(0)
if "ip route add" in line:
    sys.exit(1 if os.environ.get("FAKE_ROUTE_ADD_FAILS") else 0)
if "ip route show" in line:
    print(os.environ.get("FAKE_ROUTE", "blackhole 169.254.169.254 "))
elif "ip route del" in line:
    print("RTNETLINK answers: Operation not permitted", file=sys.stderr)
    sys.exit(2)
elif "CapEff" in line:
    print("CapEff:\t0000000000000000")
elif "curl" in line:
    sys.exit(7)
elif os.environ.get("FAKE_STDERR"):
    print(os.environ["FAKE_STDERR"], file=sys.stderr)
'''


@pytest.fixture
def fake_pc(tmp_path):
    """A small git repo with run.sh and its files, a home folder with links planted as the container could, and fake
    docker, aws and ttyd commands first on PATH."""
    repo = tmp_path / "repo"
    shutil.copytree(DEV_PC, repo / "demo_video" / "tools" / "dev_pc")
    shutil.copy(VIDEO / ".gitignore", repo / "demo_video" / ".gitignore")
    (repo / "platform_team" / "shared_code").mkdir(parents=True)
    shutil.copy(ROOT / "platform_team" / "shared_code" / "hub_env.sh", repo / "platform_team" / "shared_code")
    for rel in ("dev_team/agent_template/agent.json", "dev_team/quality_agent/agent.json",
                "dev_team/quality_agent/variants/v2-loop/agent.py", "dev_team/release_review/agent.json",
                "demo_scenes/search", "pyproject.toml", "uv.lock"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(rel + "\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    out = repo / "demo_video" / "out" / "dev-pc"
    (out / "creds").mkdir(parents=True)
    for name in ("developer.ini", "bedrock.json"):
        (out / "creds" / name).write_text("stand-in\n")
    home = out / "home"
    home.mkdir()
    victim = tmp_path / "victim"                                  # a folder of this PC outside the home
    victim.mkdir()
    (victim / "keep.txt").write_text("a file of this PC\n")       # a delete through a link would take it
    for planted in ("work", "prepared", "made-by-claude"):
        (home / planted).symlink_to(victim)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(FAKE_DOCKER.replace("PYTHON", sys.executable))
    (bin_ / "aws").write_text("#!/bin/sh\necho abcdefghij\n")
    (bin_ / "ttyd").write_text("#!/bin/sh\necho started >> \"$FAKE_LOG.ttyd\"\n")
    for f in bin_.iterdir():
        f.chmod(0o755)
    (tmp_path / "stdin").mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "DEMO_", "HUB_"))} | {
        "PATH": f"{bin_}:/usr/bin:/bin", "FAKE_LOG": str(tmp_path / "docker.log"), "FAKE_STDIN": str(tmp_path / "stdin")}

    def run(*args, **extra):
        return subprocess.run([str(repo / "demo_video/tools/dev_pc/run.sh"), *args], capture_output=True, text=True,
                              env=env | extra, timeout=60)

    def calls():
        log = tmp_path / "docker.log"
        return log.read_text().splitlines() if log.exists() else []

    def stdin(i):
        """What run.sh gave the i-th docker call on its standard input, as bytes."""
        return (tmp_path / "stdin" / str(i)).read_bytes()

    def snapshot():
        return sorted((str(p.relative_to(home)), os.readlink(p) if p.is_symlink() else None)
                      for p in home.rglob("*") if p.is_symlink() or not any(q.is_symlink() for q in p.parents))

    return dict(repo=repo, home=home, out=out, victim=victim, run=run, calls=calls, stdin=stdin, snapshot=snapshot,
                ttyd_started=lambda: (tmp_path / "docker.log.ttyd").exists())


def _members(data: bytes) -> list[str]:
    import io
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        return sorted(m.name for m in t.getmembers() if m.isfile())


def test_up_and_agent_write_inside_the_home_only_through_docker_exec_and_never_follow_a_planted_link(fake_pc):
    before = fake_pc["snapshot"]()
    r = fake_pc["run"]("up")
    assert r.returncode == 0, r.stdout + r.stderr
    r = fake_pc["run"]("agent", "quality_agent")
    assert r.returncode == 0, r.stdout + r.stderr
    # nothing reached the folder the links point to, and the home is as it was: every write went through docker exec
    assert [f.name for f in fake_pc["victim"].iterdir()] == ["keep.txt"] and fake_pc["snapshot"]() == before
    assert (fake_pc["victim"] / "keep.txt").read_text() == "a file of this PC\n"
    calls = fake_pc["calls"]()
    run_call = next(c for c in calls if c.startswith("run "))
    assert "--security-opt no-new-privileges" in run_call and "--workdir /home/dev " in run_call
    writes = [c for c in calls if c.startswith("exec") and ("tar -x" in c or "cat >" in c or "rm -rf" in c or "mv " in c)]
    assert writes and all(c.startswith("exec -u dev ") or c.startswith("exec -i -u dev ") for c in writes), writes
    # the checkout: tracked files without quality_agent; `agent` later sends the repo's tracked quality_agent
    up_tar, agent_tar = [i for i, c in enumerate(calls) if c == "exec -i -u dev hub-dev-pc tar -x -C /home/dev/work"]
    checkout = _members(fake_pc["stdin"](up_tar))
    assert "demo_scenes/search" in checkout and "dev_team/agent_template/agent.json" in checkout
    assert not [m for m in checkout if m.startswith("dev_team/quality_agent/")]
    assert _members(fake_pc["stdin"](agent_tar)) == ["dev_team/quality_agent/agent.json",
                                                     "dev_team/quality_agent/variants/v2-loop/agent.py"]
    [settings] = [i for i, c in enumerate(calls) if c.startswith("exec -i -u dev hub-dev-pc sh -c") and "settings.json" in c]
    assert fake_pc["stdin"](settings) == (DEV_PC / "settings.json").read_bytes()
    [mcp] = [i for i, c in enumerate(calls) if c.startswith("exec -i -u dev hub-dev-pc sh -c") and ".mcp.json" in c]
    assert b"/registry/abcdefghij/mcp" in fake_pc["stdin"](mcp) and b"<REGISTRY_ID>" not in fake_pc["stdin"](mcp)
    # what Claude Code wrote is moved aside inside the container, by a fixed script with the names as arguments
    [move] = [c for c in calls if "made-by-claude" in c]
    assert move.startswith("exec -u dev hub-dev-pc sh -c ") and move.split(" sh quality_agent quality_agent-")[1]
    assert not [c for c in calls if "prepared" in c and "rm -rf" not in c]


@pytest.mark.parametrize("folder", ["home", "creds", "out"])
def test_a_home_creds_or_output_folder_that_is_a_link_is_refused_in_one_line(fake_pc, folder):
    target = {"home": fake_pc["home"], "creds": fake_pc["out"] / "creds", "out": fake_pc["out"]}[folder]
    moved = target.with_name(target.name + "-real")
    target.rename(moved)
    target.symlink_to(moved)
    for sub in (["up"], ["creds"], ["agent", "quality_agent"], ["forget"]):
        r = fake_pc["run"](*sub)
        assert r.returncode == 1 and r.stdout.count("\n") == 1 and "is a symbolic link" in r.stdout, (sub, r.stdout)
    assert fake_pc["calls"]() == []


def test_up_fails_closed_when_the_metadata_route_cannot_be_set(fake_pc):
    r = fake_pc["run"]("up", FAKE_ROUTE_ADD_FAILS="1")
    assert r.returncode == 1 and "the container is removed" in r.stdout
    calls = fake_pc["calls"]()
    add = next(i for i, c in enumerate(calls) if "ip route add" in c)
    assert calls[add + 1] == "rm -f hub-dev-pc" and not [c for c in calls[add:] if "uv sync" in c or "tar -x" in c]


@pytest.mark.parametrize("sub", ["term", "check"])
def test_term_and_check_refuse_a_container_without_the_route(fake_pc, sub):
    r = fake_pc["run"](sub, FAKE_ROUTE="")
    assert r.returncode == 1 and "no blackhole route" in r.stdout
    assert not [c for c in fake_pc["calls"]() if "claude" in c or "bash" in c]
    assert not fake_pc["ttyd_started"]()


def test_check_masks_standard_error_and_shows_that_dev_holds_no_capability(fake_pc):
    r = fake_pc["run"]("check", FAKE_STDERR="arn:aws:iam::234567890123:role/x is not authorized")
    assert "234567890123" not in r.stdout + r.stderr and "<ACCOUNT>" in r.stdout + r.stderr
    assert "CapEff:\t0000000000000000 (the user dev holds no effective capability)" in r.stdout
    assert "the user dev cannot delete the route: RTNETLINK answers: Operation not permitted" in r.stdout


# ------------------------------------------------------------------ the build script: captions, cards, clips and reels

BUILD = VIDEO / "scripts" / "build.py"


def _build():
    """demo_video/scripts/build.py as a module (it is a script, not a package)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("demo_video_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _refused(spec, tmp_path, says):
    """The build stops before it writes anything, and its message names the text that broke a rule."""
    build = _build()
    with pytest.raises(SystemExit) as stop:
        build.run(spec, lang="ko", out=tmp_path / "out", check_only=True)
    assert stop.value.code == 2
    assert not (tmp_path / "out").exists()
    return says


def _with_beat(text):
    import copy
    build = _build()
    spec = copy.deepcopy(build.SPEC)
    spec["clips"]["00-home"]["beats"]["ko"] = [{"at": "shot:wide", "text": text}]
    return spec


def test_a_caption_over_45_characters_stops_the_build(tmp_path, capsys):
    text = "허브는 팀이 올린 에이전트를 자동으로 심사하고 통과한 것만 호스팅해서 모두가 쓰게 합니다"
    assert len(text) > 45
    _refused(_with_beat(text), tmp_path, text)
    out = capsys.readouterr()
    assert text in out.err and "45" in out.err
    ok = "허브가 신청을 자동으로 심사합니다"
    build = _build()
    build.run(_with_beat(ok), lang="ko", out=tmp_path / "ok", check_only=True)      # 45 or fewer passes
    assert (tmp_path / "ok" / "scripts" / "ko" / "00-home.json").exists()


@pytest.mark.parametrize("bad", ["—", "·", "→"])
def test_a_caption_with_a_middle_dot_dash_or_arrow_stops_the_build(tmp_path, capsys, bad):
    text = f"팀이 신청하면 {bad} 허브가 심사합니다"
    _refused(_with_beat(text), tmp_path, text)
    assert text in capsys.readouterr().err


@pytest.mark.parametrize("text", ["허브가 신청을 자동으로 심사", "허브가 신청을 자동으로 심사한다", "허브가 심사합니다. 그리고 올립니다",
                                  "허브가 심사할까요?"])
def test_a_caption_that_is_not_hamnida_style_stops_the_build(tmp_path, capsys, text):
    # one sentence in the 합니다 style: it ends in 니다, and nothing ends before it
    _refused(_with_beat(text), tmp_path, text)
    assert text in capsys.readouterr().err


@pytest.mark.parametrize("text", ["4배속으로 심사가 끝납니다", "이 녹화에서는 반려 버튼을 누르지 않았습니다"])
def test_a_caption_with_a_speed_label_or_a_recording_note_stops_the_build(tmp_path, capsys, text):
    _refused(_with_beat(text), tmp_path, text)
    assert text in capsys.readouterr().err


def test_a_dimension_is_not_a_speed_label(tmp_path, capsys):
    # the part's specification that 26-answers shows may be quoted in a caption; a speed label still stops the build
    build = _build()
    build.run(_with_beat("P-100의 규격은 M4 x 12 mm, 강철입니다"), lang="ko", out=tmp_path / "ok", check_only=True)
    for text in ("심사를 4x로 빠르게 봅니다", "심사를 1.25× 속도로 봅니다"):
        _refused(_with_beat(text), tmp_path, text)
        assert text in capsys.readouterr().err


def test_a_stage_over_its_caption_budget_stops_the_build(tmp_path, capsys):
    # 준비 may carry five captions in all; a sixth is refused
    build = _build()
    assert build.BUDGET == {0: 5, 1: 11, 2: 12, 3: 8, 4: 10, 5: 18}
    import copy
    spec = copy.deepcopy(build.SPEC)
    spec["clips"]["00-home"]["beats"]["ko"] = [{"at": "shot:wide", "text": "허브가 신청을 자동으로 심사합니다"}] * 6
    _refused(spec, tmp_path, "준비")
    assert "준비" in capsys.readouterr().err


def test_every_reel_names_only_clips_the_build_defines(tmp_path, capsys):
    build = _build()
    spec = build.SPEC
    names = set(spec["clips"]) | set(spec["cards"]["ko"])
    assert set(spec["reels"]) == {"main", "stage-1", "stage-2", "stage-3", "stage-4", "stage-5"}
    for reel, segments in spec["reels"].items():
        for seg in segments:
            assert build.segment_name(seg) in names, (reel, seg)
    # every take of the script is a clip of the main reel, in the order the takes are recorded
    takes = ["00-home", "11-find", "12-make", "13-submit", "21-review", "22-works", "23-reject", "24-again",
             "25-approved", "26-answers", "31-logonly", "32-passes", "33-record", "41-enforce", "42-blocked",
             "43-before", "44-attach", "45-after", "51-usage", "52-incident", "53-alarm", "54-stop", "55-neighbours",
             "56-cause", "57-back"]
    main = [build.segment_name(s) for s in spec["reels"]["main"]]
    assert [n for n in main if n in spec["clips"]] == takes
    assert main[0] == "card-intro" and main[-2:] == ["card-summary", "card-closing"]
    # a reel that names something the build does not define is refused before anything is written
    import copy
    bad = copy.deepcopy(spec)
    bad["reels"]["stage-2"].append("27-nowhere")
    _refused(bad, tmp_path, "27-nowhere")
    assert "27-nowhere" in capsys.readouterr().err


CARDS_OF_THE_PLAN = {
    "card-intro": ["AI 에이전트 호스팅 허브 on Amazon Bedrock AgentCore", "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다"],
    "card-ch0": ["준비", "플랫폼팀이 허브를 한 번 만들어 둡니다", "허브 화면의 홈"],
    "card-ch1": ["1단계. 호스팅 신청", "팀은 플랫폼팀 없이 찾고, 만들고, 신청합니다", "Claude Code와 AWS Agent Registry"],
    "card-ch2": ["2단계. 호스팅 심사", "신청이 들어오면 허브가 자동으로 심사합니다", "심사 파이프라인과 AgentCore Runtime"],
    "card-ch3": ["3단계. 전사 정책 시험", "새 전사 정책을 막지 않고 먼저 시험합니다", "Policy in AgentCore의 기록 모드"],
    "card-ch4": ["4단계. 전사 정책 적용", "전사 정책 하나가 모든 에이전트에 걸립니다", "AgentCore Gateway와 커스텀 가드레일"],
    "card-ch5": ["5단계. 이상 대응", "문제를 일으킨 에이전트 하나만 멈춥니다", "CloudWatch 알람과 AgentCore Runtime"],
    "card-compare": ["가드레일 두 가지", "기본 제공 가드레일과 커스텀 가드레일", "기본 제공은 설정으로 걸고 기록 모드로 먼저 시험합니다",
                     "커스텀은 사내 코드로 막고 민감 정보를 가립니다", "둘 다 게이트웨이에 걸려 모든 에이전트에 적용됩니다"],
    "card-summary": ["정리", "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다", "팀은 카탈로그에서 찾고 템플릿으로 만들어 스스로 신청합니다",
                     "허브가 자동으로 심사하고 통과한 것만 올립니다", "전사 정책은 게이트웨이에 한 번 걸면 모두에 적용됩니다",
                     "이상 에이전트 하나만 멈추고 이웃은 계속 답합니다"],
    # the script's one row "AgentCore는 Runtime, Gateway, Policy, Registry, 관측을 줍니다" is 54 characters: the same
    # words in two rows of at most 45
    "card-closing": ["누가 무엇을 맡나", "AgentCore가 주는 것과 플랫폼팀이 만드는 것", "AgentCore는 Runtime, Gateway, Policy를 줍니다",
                     "AgentCore는 Registry와 관측도 줍니다", "플랫폼팀은 심사 파이프라인과 운영 명령, 허브 화면을 만듭니다"],
}
SECONDS_OF_THE_PLAN = {"card-intro": 4, "card-compare": 8, "card-summary": 9, "card-closing": 7}


def test_the_cards_of_the_plan_pass_the_rules(tmp_path):
    build = _build()
    cards = build.SPEC["cards"]["ko"]
    assert {name: build.card_texts(card) for name, card in cards.items()} == CARDS_OF_THE_PLAN
    assert {n: cards[n]["seconds"] for n in SECONDS_OF_THE_PLAN} == SECONDS_OF_THE_PLAN
    # the whole build file passes its own rules: the plan's cards, and every clip with no beats yet
    r = subprocess.run([sys.executable, str(BUILD), "--check", "--lang", "ko", "--out", str(tmp_path / "out")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    written = json.loads((tmp_path / "out" / "cards" / "ko" / "cards.json").read_text(encoding="utf-8"))
    # the plugin's card format: the last row of the comparison and of the summary card is the accent
    assert written["card-summary"]["lines"][-1] == ["row", "이상 에이전트 하나만 멈추고 이웃은 계속 답합니다", "accent"]
    assert written["card-compare"]["lines"][-1][-1] == "accent" and written["card-intro"]["seconds"] == 4
    assert written["card-ch1"]["lines"][0] == ["kicker", "1단계. 호스팅 신청"]
    manifest = json.loads((tmp_path / "out" / "reels" / "hosting-hub-main-ko.json").read_text(encoding="utf-8"))
    assert manifest["segments"][0]["file"] == "cards/ko/card-intro.mp4"
    assert {"file": "clips/ko/00-home.mp4"} in [{"file": s["file"]} for s in manifest["segments"]]
    script = json.loads((tmp_path / "out" / "scripts" / "ko" / "00-home.json").read_text(encoding="utf-8"))
    assert script["beats"] == [] and script["speed"] == 1.25 and "title" not in script


def test_a_card_title_or_row_that_breaks_a_rule_stops_the_build(tmp_path, capsys):
    import copy
    build = _build()
    spec = copy.deepcopy(build.SPEC)
    spec["cards"]["ko"]["card-summary"]["rows"][0] = "팀은 카탈로그에서 찾고 템플릿으로 만들어 스스로 신청"
    _refused(spec, tmp_path, "신청")
    assert "팀은 카탈로그에서 찾고 템플릿으로 만들어 스스로 신청" in capsys.readouterr().err


def test_without_check_the_build_needs_the_plugin_and_the_raw_takes(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DEMO_VIDEO_PLUGIN"}
    r = subprocess.run([sys.executable, str(BUILD), "--lang", "ko", "--out", str(tmp_path / "out")],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "DEMO_VIDEO_PLUGIN" in r.stderr
    assert "https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video" in r.stderr
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    for f in ("edit_demo.py", "make_cards.py"):
        (plugin / f).write_text("raise SystemExit(9)\n")
    r = subprocess.run([sys.executable, str(BUILD), "--lang", "ko", "--out", str(tmp_path / "out")],
                       capture_output=True, text=True, env=env | {"DEMO_VIDEO_PLUGIN": str(plugin)}, timeout=60)
    assert r.returncode == 1 and "raw/00-home.webm" in r.stderr                 # no raw take: nothing is cut


def test_a_clip_with_no_beats_is_cut_without_captions(tmp_path):
    # the plugin's clip falls back to the camera's shot labels when a script has no beats: those are notes for the
    # person who records, never captions
    build = _build()
    cmd = build.clip_command(Path("/plugin"), "00-home", build.SPEC["clips"]["00-home"], "ko", tmp_path)
    assert "--no-captions" in cmd and "--title" not in cmd


# ------------------------------------------------------------------ the recording: record.sh, the user's shell, storyboards

SCENES = VIDEO / "scenes"
TAKES = ["00-home", "11-find", "13-submit", "21-review", "22-works", "23-reject", "24-again", "25-approved",
         "26-answers",                                  # 12-make is the second part of the 11-find recording
         "31-logonly", "32-passes", "33-record", "41-enforce", "42-blocked", "43-before", "44-attach", "45-after",
         "51-usage", "52-incident", "53-alarm", "54-stop", "55-neighbours", "56-cause", "57-back"]
NODE = shutil.which("node")


def test_the_users_shell_is_on_this_pc_only_with_its_prompt_and_the_scene_commands():
    sh = VIDEO / "tools" / "user_shell.sh"
    assert os.access(sh, os.X_OK)
    code = _code(sh)
    assert "set -euo pipefail" in code and "set -x" not in code
    [ttyd] = [line for line in code.splitlines() if "ttyd -i lo" in line]
    assert re.search(r'\bttyd -i lo -p "\$port" -O -w "\$repo"', ttyd) and "port=7682" in code
    assert "PS1='사용자 $ '" in code and 'PATH="$PATH:$repo/demo_scenes"' in code         # the scene commands last
    assert "bash --norc --noprofile -i" in code and "HISTFILE=" in code                 # no rc file, no history
    assert 'AWS_REGION="$region" AWS_DEFAULT_REGION="$region" DEMO_PREFIX="$prefix"' in code
    for word in ("--env-file", ".aws", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "0.0.0.0"):
        assert word not in code, word
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")} | {"PATH": "/usr/bin:/bin"}
    for args in ([], ["nope"], ["up", "x"]):
        r = subprocess.run([str(sh), *args], capture_output=True, text=True, env=env, timeout=30)
        assert (r.returncode, r.stdout) == (2, "usage: demo_video/tools/user_shell.sh up | down\n"), args


def test_record_sh_refuses_bad_usage_an_unknown_take_or_a_missing_tool_before_recording(tmp_path):
    rec = SCENES / "record.sh"
    assert os.access(rec, os.X_OK)
    env = {k: v for k, v in os.environ.items() if k not in ("DEMO_VIDEO_PLUGIN", "PLAYWRIGHT_ROOT")}
    run = lambda *a, **e: subprocess.run([str(rec), *a], capture_output=True, text=True, env=env | e, timeout=30)
    usage = "usage: demo_video/scenes/record.sh <take> [max seconds] [--lang ko]\n"
    assert (run().returncode, run().stdout) == (2, usage)
    assert run("00-home", "120", "x").stdout == usage and run("00-home", "--lang").stdout == usage
    for take in ("99-nowhere", "../lib", "lib"):
        r = run(take)
        assert r.returncode == 2 and r.stdout.startswith(f"no take '{take}'"), take
    r = run("00-home")
    assert r.returncode == 2 and "DEMO_VIDEO_PLUGIN" in r.stdout and "plugins/demo-video" in r.stdout
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "record_demo.mjs").write_text("")
    r = run("00-home", DEMO_VIDEO_PLUGIN=str(plugin), PLAYWRIGHT_ROOT=str(tmp_path))
    assert r.returncode == 2 and "PLAYWRIGHT_ROOT" in r.stdout
    assert not (ROOT / "demo_video" / "out" / "raw" / "99-nowhere.webm").exists()


def _storyboards():
    return sorted(SCENES.glob("*/storyboard.mjs"))


def test_every_storyboard_names_its_surfaces_checks_the_hubs_state_first_and_reads_the_language():
    assert [p.parent.name for p in _storyboards()] == TAKES
    for p in _storyboards():
        text = p.read_text(encoding="utf-8")
        [line] = [line for line in text.splitlines() if line.startswith("export const surfaces")]
        names = re.fullmatch(r"export const surfaces = \[((?:'\w+'(?:, )?)+)\];", line).group(1)
        assert set(re.findall(r"'(\w+)'", names)) <= {"hub", "dev", "user"}, p
        body = text.split("export default async function storyboard(", 1)[1]
        first = re.search(r"\bawait\s+([\w.]+)\(", body).group(1)
        assert first == "needState", (p, first)                 # the state check comes before anything else
        assert "texts(option)" in text, p
        # every text a take types or waits for lives in lib/texts.mjs under its language
        assert not re.search(r"[가-힣]", text), p


def test_the_recording_files_name_no_host_home_folder_person_or_account():
    files = [*SCENES.rglob("*.mjs"), *SCENES.rglob("*.py"), *SCENES.rglob("*.sh"), VIDEO / "tools" / "user_shell.sh",
             VIDEO / "scripts" / "build.py", ROOT / "tests" / "claude_code_dialogs.json"]
    assert len(files) > 10
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text.replace("123456789012", "")), f
        assert not re.search(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}", text), f
        assert "/home/ubuntu" not in text and "ip-172-" not in text and "arn:aws" not in text, f
    # the plugin and Playwright are found through the environment, never a path of this PC
    assert "process.env.DEMO_VIDEO_PLUGIN" in (SCENES / "lib" / "plugin.mjs").read_text(encoding="utf-8")


# A stand-in for the plugin's term.mjs: the page is scripted (page.next() gives the next screen's rows, the last one
# repeats) and every key and paste is written to page.log.
STAND_IN_TERM = """
export const screenText = async page => page.next().join('\\n');
export const paste = async (page, text) => { page.log.push(['paste', text, page.looked()]); };
export const type = async (page, text) => { page.log.push(['type', text]); };
export const waitPrompt = async () => true;
export const waitFor = async () => true;
export const rowsRect = async () => null;
"""
FAKE_PAGE = """
const fakePage = screens => {
  let i = 0, last = null;
  const page = { log: [], next: () => (last = screens[Math.min(i++, screens.length - 1)]),
    // the screen the driver had looked at last (null before its first look)
    looked: () => (last === null ? null : last.join('\\n')),
    waitForTimeout: async () => {},
    // each key (and each paste, in term.mjs) is logged with the screen the driver had looked at last
    keyboard: { press: async key => { page.log.push(['key', key, page.looked()]); } } };
  return page;
};
const fakeRec = () => ({ notes: [], note(kind, data) { this.notes.push([kind, data]); }, now: () => 1 });
const fakeCam = () => ({ kept: [], shots: [], keep(text) { this.kept.push(text); }, lines: async (k) => {}, reset: async () => {},
  hold: async () => {} });
"""


def _node(script: str, tmp_path: Path) -> str:
    """Run an ES module snippet in demo_video/scenes/lib/, with a stand-in for the plugin's term.mjs."""
    plugin = tmp_path / "plugin"
    plugin.mkdir(exist_ok=True)
    (plugin / "term.mjs").write_text(STAND_IN_TERM)
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30,
                       cwd=SCENES / "lib", env=os.environ | {"DEMO_VIDEO_PLUGIN": str(plugin)})
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_state_check_says_what_differs(tmp_path):
    out = _node("""
import { differences } from './state.mjs';
const s = { records: { docs_adk: { type: 'AGENT', status: 'APPROVED' }, quality_agent: { type: 'AGENT', status: 'PENDING_APPROVAL' } },
            reviewing: ['quality_agent'], mode: null, attached: false, stopped: [] };
console.log(JSON.stringify([
  differences(s, { records: { docs_adk: 'APPROVED', quality_agent: ['PENDING_APPROVAL', 'REJECTED'] }, reviewing: ['quality_agent'],
                   mode: null, attached: false, stopped: [] }),
  differences(s, { records: { release_review: 'APPROVED', quality_agent: 'absent' }, reviewing: [], mode: 'active',
                   attached: true, stopped: ['quality_agent'] }),
]));""", tmp_path)
    same, other = json.loads(out)
    assert same == []
    assert other == ["release_review is absent, not APPROVED", "quality_agent is PENDING_APPROVAL, not absent",
                     "reviews running: quality_agent (this take needs none)", "guard_prompt is off, not active",
                     "the custom guardrail is detached", "stopped: none"]


DIALOGS = json.loads((ROOT / "tests" / "claude_code_dialogs.json").read_text(encoding="utf-8"))


def _shell_screen(command_rows: list[str]) -> list[str]:
    """The real Bash question of the recorded take (its fourth question, the one that also offered "2. Yes, and don't
    ask again for: cd *"), with its command rows replaced: each row behind the dialog's gutter."""
    rows = list(DIALOGS["take_ask4"])
    first = next(i for i, r in enumerate(rows) if r.startswith(" │ "))
    last = max(i for i, r in enumerate(rows[:rows.index(" Do you want to proceed?")]) if r.startswith(" │ ")
               and not r.startswith(" │ Compound"))
    return rows[:first] + [f" │ {r}" for r in command_rows] + rows[last + 1:]


def _file_screen(path_row: str) -> list[str]:
    """The real file question of an earlier attempt (create main.py), with its path row replaced (and the question
    naming that path's file)."""
    rows = list(DIALOGS["attempt4_create_main"])
    i = rows.index(" Create file")
    name = path_row.rsplit("/", 1)[-1]
    return [r.replace("Do you want to create main.py?", f"Do you want to create {name}?")
            for r in rows[:i + 1] + [f" {path_row}"] + rows[i + 2:]]


READS = [["cat dev_team/agent_template/README.md"], ["ls -la dev_team/agent_template dev_team/release_review"],
         ["cd /home/dev/work/dev_team; ls agent_template"], ["grep -n -A1 -E '^name = \"strands-agents\"' uv.lock"],
         ["sed -n 1,40p dev_team/agent_template/agent.py | head -20"], ["cd dev_team && cat agent_template/agent.json"],
         ["find dev_team/agent_template -name '*.py'"], ["wc -l uv.lock 2>/dev/null"]]
# the ways past a check of the command's text that the reviews found, in the layout Claude Code prints
BYPASSES = [["python3 quality_agent/agent.py"], ["publish quality_agent"], ["uv run pytest tests"],
            ['bash -c "python3 agent.py"'], ["cp quality_agent/agent.py ../demo_scenes/search"],
            ["echo \"v: $(python3 -c 'print(1)')\""], ["env python3 x.py"], ["timeout 30 python3 x.py"],
            ["if python3 x.py; then ls; fi"], ["cat `python3 x.py`"], ["{ python3 -c 1; }"], ["uvx ruff check"],
            ["make test"], ["cat <<EOF", "$(python3 x.py)", "EOF"], ["echo x >| ../demo_scenes/search"],
            ["rsync -a quality_agent/ ../demo_scenes/search"], ["find ../platform_team -name x -delete"],
            ['sed -n "w ../demo_scenes/search" uv.lock'], ["tar -xf a.tar -C .."],
            ["cat quality_agent/agent.json", "echo 'Do you want to proceed'", "python3 x.py"],
            ["python3 x.py # Do you want to create agent.py?"],
            ["mkdir quality_agent && cp agent_template/main.py quality_agent/"],
            ['echo "strands-agents==1.65.0" >> quality_agent/requirements.txt'],
            ["cat /run/dev-pc/bedrock.json"], ["cd .. && ls"], ["cd /tmp"], ["cat ~/.claude.json"], ["ls &"],
            ["cat quality_agent/agent.py | sh"], ["xargs cat < files.txt"], ["find . -exec cat {} +"],
            ["sed -i s/a/b/ uv.lock"], ["awk '{print > \"x\"}' uv.lock"], ["ls $(echo /tmp)"], ["cat $HOME/x"],
            ['cat "/run/dev-pc/bedrock.json"'], ["grep --file=/run/dev-pc/bedrock.json x uv.lock"],
            ["sort -uo x uv.lock"], ["cat uv.lock 3>/tmp/y"], ["cat ../../../etc/passwd"], ["FOO=1 cat uv.lock"],
            # the second review's
            ["sort --compress-program=sh -S 1 dev_team/quality_agent/notes.txt"],
            ["sort --compress-program sh -S 1 dev_team/quality_agent/notes.txt"],
            ["sort --compress-program=python3 --buffer-size=1 dev_team/quality_agent/notes.txt"],
            ["sort --compress-program=publish -S 1 uv.lock"], ["cat uv.lock | sort --compress-program=bash -S 1"],
            ["sort uv.lock --compress-program=sh -S 1"], ["sort --o=search uv.lock"], ["sort --out=x uv.lock"],
            ["sort --outp=x uv.lock"], ["cd demo_scenes; sort --out=search /home/dev/work/dev_team/quality_agent/notes.txt"],
            ["cat dev_team/quality_agent/notes.txt >&1x"],
            ["cd demo_scenes && cat /home/dev/work/dev_team/quality_agent/notes.txt >&2search"],
            ["cd dev_team/zz; find /home/dev/work/demo_scenes *"], ["cd dev_team/zz; sort *"],
            ["cat .?/.?/.?/run/dev-pc/bedrock.json"], ["cat /home/dev/work/.[.]/.[.]/.[.]/run/dev-pc/bedrock.json"],
            ["cat dev_team/agent_template/README.md; ls quality_agent…"]]
FILE_PATHS = ["/home/dev/work/dev_team/quality_agent/agent.py", "~/work/dev_team/quality_agent/requirements.txt",
              "quality_agent/main.py", "dev_team/quality_agent/main.py", "/home/dev/work/demo_scenes/search",
              "/home/dev/work/dev_team/quality_agent/../../demo_scenes/search",
              "/home/dev/work/dev_team/quality_agent/.claude/settings.json"]


def _every_dialog_screen() -> list[list[str]]:
    """The seven real dialogs kept from the takes, and every command and path of both reviews in that layout."""
    return ([DIALOGS[k] for k in DIALOGS] + [_shell_screen(c) for c in READS + BYPASSES]
            + [_file_screen(p) for p in FILE_PATHS])


def _requests(cases: dict, tmp_path) -> dict:
    """Run request() once per case against a scripted page; per case: the keys (with the screen the driver had looked
    at last), the pastes, the notes and the error, if any."""
    given = tmp_path / "cases.json"
    given.write_text(json.dumps(cases), encoding="utf-8")
    run = """import fs from 'node:fs';
import { request } from './claude.mjs';
""" + FAKE_PAGE + f"""
const cases = JSON.parse(fs.readFileSync({json.dumps(str(given))}, 'utf8'));
""" + """const out = {};
for (const [name, screens] of Object.entries(cases)) {
  const page = fakePage(screens), rec = fakeRec(), cam = fakeCam();
  let error = '';
  try { await request(page, rec, cam, 'the request', { noRun: 'files only', idleMs: 0 }); } catch (e) { error = e.message; }
  out[name] = { keys: page.log.filter(l => l[0] === 'key').map(l => [l[1], l[2]]),
                pastes: page.log.filter(l => l[0] === 'paste').map(l => l[1]),
                pasted_on: page.log.filter(l => l[0] === 'paste').map(l => l[2]), notes: rec.notes, error };
}
console.log(JSON.stringify(out));"""
    return json.loads(_node(run, tmp_path))


BUSY = ["✻ Cooking… (2s · esc to interrupt)"]
DONE = ["✻ Cooked for 3s", "❯"]


def _answered_with_escape_only(g: dict, dialog: list[str], name) -> None:
    """Every key sent while the dialog was the screen looked at last is Escape, and nothing was pasted onto it: each
    paste follows a look, and that look did not find the dialog."""
    shown = "\n".join(dialog)
    for key, screen in g["keys"]:
        if screen == shown:
            assert key == "Escape", (name, key)                  # never Enter, nor any other key, on a dialog
    for screen in g["pasted_on"]:
        assert screen is not None and screen != shown, name


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_while_a_dialog_is_on_the_screen_the_only_key_is_escape_and_enter_never_meets_an_option_row(tmp_path):
    # the storyboard never answers Yes: whatever the question (every kept real one, every command and path of both
    # reviews), it presses Escape, then sends the take's sentence; Enter goes out only after a look that finds no
    # option row (here the dialog is still there at the look before the sentence: Escape again, look again)
    screens = _every_dialog_screen()
    assert len(screens) == 7 + len(READS) + len(BYPASSES) + len(FILE_PATHS)
    got = _requests({str(i): [BUSY, BUSY, s, s, BUSY, BUSY, DONE] for i, s in enumerate(screens)}, tmp_path)
    for i, s in enumerate(screens):
        g = got[str(i)]
        assert g["error"] == "", (i, g["error"])
        _answered_with_escape_only(g, s, i)
        assert [k for k, _ in g["keys"]] == ["Enter", "Escape", "Escape", "Enter"], i
        assert g["pastes"] == ["the request", "files only"], i
        assert [n for n in g["notes"] if n[0] == "permission"] == [["permission", {"answer": "no", "kind": n[1]["kind"]}]
                                                                   for n in g["notes"] if n[0] == "permission"]
        assert len([n for n in g["notes"] if n[0] == "permission"]) == 1, i


# A question Claude Code draws itself, whose option texts the other agent writes (they read neither Yes nor No).
OWN_QUESTION = ["────────────────────────────────────────────────────────────────────────────────────────────────────",
                " ☐ 실행 방식", "", "파일을 만든 뒤 어떻게 할까요?", "",
                "❯ 1. 네, 실행합니다", "     지금 셸에서 돌려 봅니다", "  2. 아니요", "     파일만 둡니다",
                "  3. Type something.", "", "Enter to select · ↑/↓ to navigate · Esc to cancel"]
# An answer of Claude Code with a plain numbered list: no marker, and no row that reads Yes or No.
PLAIN_LIST = ["● 읽은 파일입니다.", "  1. agent.py를 읽었습니다", "  2. hub_tools.py에는 도구 호출이 있습니다", "",
              "✻ Cooked for 3s", "❯"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_dialog_whose_options_read_neither_yes_nor_no_gets_escape_and_a_plain_numbered_list_does_not(tmp_path):
    got = _requests({"during": [BUSY, BUSY, OWN_QUESTION, OWN_QUESTION, BUSY, BUSY, DONE],
                     "left_open": [OWN_QUESTION, BUSY, BUSY, BUSY, DONE],
                     "plain": [PLAIN_LIST, PLAIN_LIST, BUSY, DONE]}, tmp_path)
    during, left_open, plain = got["during"], got["left_open"], got["plain"]
    assert [n for n in during["notes"] if n[0] == "permission"] == [["permission", {"answer": "no", "kind": "unknown"}]]
    assert [k for k, _ in during["keys"]] == ["Enter", "Escape", "Escape", "Enter"]
    assert [k for k, _ in left_open["keys"]] == ["Escape", "Enter"]       # the open dialog first, then the request
    for name in ("during", "left_open"):
        assert got[name]["error"] == "", name
        _answered_with_escape_only(got[name], OWN_QUESTION, name)
    # an answer's numbered list is not a dialog: the request goes out with Enter, nothing is answered
    assert [k for k, _ in plain["keys"]] == ["Enter"] and plain["error"] == ""
    assert not [n for n in plain["notes"] if n[0] == "permission"]


def _wrapped_question() -> list[str]:
    """The real file question (create main.py) for a file whose long name wraps the asking row over two rows."""
    name = "inspection_retry_notes_for_the_quality_agent_written_while_reading_its_log_lines_today.py"
    rows = _file_screen(f"/home/dev/work/dev_team/quality_agent/{name}")
    i = rows.index(f" Do you want to create {name}?")
    return rows[:i] + [" Do you want to create", f" {name}?"] + rows[i + 1:]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_permission_question_whose_asking_row_wraps_is_still_answered_with_escape(tmp_path):
    wrapped = _wrapped_question()
    g = _requests({"wrapped": [BUSY, BUSY, wrapped, wrapped, BUSY, BUSY, DONE]}, tmp_path)["wrapped"]
    assert [n for n in g["notes"] if n[0] == "permission"] == [["permission", {"answer": "no", "kind": "file"}]]
    assert [k for k, _ in g["keys"]] == ["Enter", "Escape", "Escape", "Enter"]
    assert g["error"] == ""
    _answered_with_escape_only(g, wrapped, "wrapped")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_nothing_is_pasted_onto_an_open_dialog(tmp_path):
    # a dialog still open when the request is to be pasted, and one still open when the take's sentence is to be
    # pasted after the Escape: each paste waits for a look that finds no dialog
    dialog = DIALOGS["take_ask1"]
    got = _requests({"request": [dialog, BUSY, BUSY, BUSY, DONE],
                     "sentence": [BUSY, BUSY, dialog, dialog, BUSY, BUSY, DONE]}, tmp_path)
    for name, g in got.items():
        assert g["error"] == "", name
        _answered_with_escape_only(g, dialog, name)
    assert got["request"]["pastes"] == ["the request"]
    assert got["sentence"]["pastes"] == ["the request", "files only"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_row_that_only_resembles_a_question_does_not_start_the_answering_branch(tmp_path):
    seems = ["● agent.py는 120줄입니다. Do you want to see the rest of it?", BUSY[0]]
    got = _requests({"seems": [BUSY, seems, seems, DONE]}, tmp_path)["seems"]
    assert [k for k, _ in got["keys"]] == ["Enter"] and got["error"] == ""
    assert not [n for n in got["notes"] if n[0] == "permission"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_an_option_row_in_claude_codes_answer_holds_back_enter_and_stops_the_take_when_it_stays(tmp_path):
    answer = ["● 확인한 것:", "  1. Yes, agent.json is there", "  2. No requirements.txt yet", "❯"]
    got = _requests({"stays": [answer], "goes": [answer, DONE, DONE, BUSY, DONE]}, tmp_path)
    assert [k for k, _ in got["stays"]["keys"]] == ["Escape"]
    assert got["stays"]["error"].startswith("an option row stays on the screen")
    assert [k for k, _ in got["goes"]["keys"]] == ["Escape", "Enter"] and got["goes"]["error"] == ""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_every_screen_a_claude_code_session_shows_is_kept_for_the_text_check(tmp_path):
    run = """import { request } from './claude.mjs';
import { kit } from './take.mjs';
""" + FAKE_PAGE + """
const screens = [['✻ Cooking… (1s · esc to interrupt)'], ['✻ Cooking… (1s · esc to interrupt)'],
                 ['arn:aws:iam::123456789012:role/x', '✻ Cooking… (2s · esc to interrupt)'], ['✻ Cooked for 3s']];
const page = fakePage(screens), rec = fakeRec(), cam = fakeCam();
await request(page, rec, cam, 'x', { idleMs: 0 });
const k = kit({ page: { evaluate: async () => '' }, rec, option: (n, d) => ({ '--out': %s, '--name': 'take' })[n] ?? d });
k.keep('a'); k.keep('a'); k.keep('b');
console.log(JSON.stringify(cam.kept));""" % json.dumps(str(tmp_path))
    kept = json.loads(_node(run, tmp_path))
    # each screen not seen before, in order (the repeated one once)
    assert kept == [s for s in ["✻ Cooking… (1s · esc to interrupt)",
                                "arn:aws:iam::123456789012:role/x\n✻ Cooking… (2s · esc to interrupt)",
                                "✻ Cooked for 3s"]]
    text = (tmp_path / "take.texts.txt").read_text(encoding="utf-8")
    assert text.count("\na\n") == 1 and text.count("\nb\n") == 1 and text.count("== ") == 2


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_job_is_followed_until_the_pages_one_reload_or_until_no_reload_can_come(tmp_path):
    out = _node("""import { jobEnded } from './hub.mjs';
const cases = [
  { first: '', state: '', reloaded: false },                 // no job panel yet
  { first: 'running', state: 'running', reloaded: false },   // drawn running: the page will reload when it ends
  { first: 'running', state: 'done', reloaded: false },      // (a finished state before the reload is not possible)
  { first: 'running', state: 'done', reloaded: true },       // the reload came
  { first: 'running', state: 'failed', reloaded: true },
  { first: 'done', state: 'done', reloaded: false },         // drawn finished: the page follows no job, no reload
];
console.log(JSON.stringify(cases.map(jobEnded)));""", tmp_path)
    assert json.loads(out) == [False, False, False, True, True, True]


def test_the_text_check_masks_the_containers_name_instead_of_dropping_its_line(tmp_path):
    check = SCENES / "lib" / "check_texts.sh"
    texts = tmp_path / "take.texts.txt"
    texts.write_text("== 1.0 shell\ndev@dev-pc:~/work$ echo 123456789012\n== 2.0 end\ndev@dev-pc:~/work$\n")
    r = subprocess.run([str(check), str(texts)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "123456789012" not in r.stdout and "<12 digits>" in r.stdout
    texts.write_text("== 1.0 shell\ndev@dev-pc:~/work$ ls\n== 2.0 end\nwrite to someone@example.com\n")
    r = subprocess.run([str(check), str(texts)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "someone@example.com" in r.stdout and "dev@dev-pc" not in r.stdout
    texts.write_text("== 1.0 shell\nids 123456789012,234567890123 here\n")
    r = subprocess.run([str(check), str(texts)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "123456789012" not in r.stdout and "234567890123" not in r.stdout
    assert "<12 digits>,<12 digits>" in r.stdout
    texts.write_text("== 1.0 shell\ndev@dev-pc:~/work$ ls\n")
    r = subprocess.run([str(check), str(texts)], capture_output=True, text=True, timeout=30)
    assert (r.returncode, r.stdout) == (0, "texts: no 12-digit number and no e-mail address in 1 screens\n")


def test_the_hubs_state_names_each_running_review_by_its_agent():
    import importlib.util
    from tests.fakes import FakeClients
    spec = importlib.util.spec_from_file_location("hub_state_take", SCENES / "lib" / "hub_state.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    c = FakeClients(running=[("first", "rid-release"), ("second", "rid-gone")])
    machine = "arn:aws:states:us-west-2:123456789012:stateMachine:hub-review"
    assert module.reviewing(c, machine, {"rid-release": "release_review"}) == ["?", "release_review"]
    assert module.reviewing(FakeClients(), machine, {}) == []
