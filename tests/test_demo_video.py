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
          "Edit(./.mcp.json)", "Edit(./pyproject.toml)", "Edit(./uv.lock)"]
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
