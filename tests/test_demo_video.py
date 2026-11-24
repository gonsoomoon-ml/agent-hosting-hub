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
          # list or instructions file that a later session would load; directly under dev_team/ by name (so that no
          # reading of **/ decides it), and in any folder below it
          "Edit(./dev_team/.claude/**)", "Edit(./dev_team/.mcp.json)", "Edit(./dev_team/CLAUDE.md)",
          "Edit(./dev_team/**/.claude/**)", "Edit(./dev_team/**/.mcp.json)", "Edit(./dev_team/**/CLAUDE.md)",
          # Claude Code's own files in the container's home, which run.sh up keeps
          "Edit(~/.claude/**)", "Edit(~/.claude.json)"]
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


def test_no_pre_allowed_rule_is_broader_than_the_list():
    allow = _settings()["permissions"]["allow"]
    # each Bash rule is one command word, each Edit rule stays under dev_team/, the MCP rule names the one server
    assert sorted(re.fullmatch(r"Bash\((\w+):\*\)", a).group(1) for a in allow if a.startswith("Bash(")) == [
        "cat", "logs", "ls", "search"]
    assert [a for a in allow if a.startswith("Edit(")] == ["Edit(./dev_team/**)"]
    assert [a for a in allow if a.startswith("mcp__")] == [f"mcp__{SERVER}__*"]
    assert not [a for a in allow if a.startswith(("Read(", "Write(", "WebFetch", "WebSearch", "Agent", "Task"))]


def _named_by(path: str, rules: list[str]) -> list[str]:
    """The Edit rules that name a path without any pattern: the path itself, or a folder of it followed by a closing
    /** (a rule with any other * is skipped, so no reading of a pattern decides it)."""
    named = []
    for rule in (r for r in rules if r.startswith("Edit(")):
        p = rule[len("Edit("):-1]
        if "*" in p.removesuffix("/**"):
            continue
        if p == path or (p.endswith("/**") and path.startswith(p.removesuffix("**"))):
            named.append(rule)
    return named


def test_every_file_a_later_session_loads_from_dev_team_or_the_home_is_named_by_a_deny_rule():
    # Edit(./dev_team/**) lets Claude Code write under dev_team/ without a question. A Claude Code folder (a skill, a
    # hook, settings), an MCP server list or an instructions file directly under dev_team/ would be loaded by a later
    # session, and so would Claude Code's own files in the container's home, which run.sh up keeps. Each is named by a
    # deny rule as it is written, with no pattern but a closing /**: how Claude Code reads **/ does not decide it.
    deny = _settings()["permissions"]["deny"]
    for path in ("./dev_team/CLAUDE.md", "./dev_team/.mcp.json", "./dev_team/.claude/settings.json",
                 "./dev_team/.claude/skills/y/SKILL.md", "~/.claude.json", "~/.claude/settings.json",
                 "~/.claude/skills/y/SKILL.md"):
        assert _named_by(path, deny), path
    for path in ("./dev_team/quality_agent/agent.py", "./dev_team/CLAUDE.md.txt", "./dev_team/.claude-notes/x"):
        assert not _named_by(path, deny), path


def test_in_the_tests_own_fnmatch_reading_the_patterns_are_written_as_meant():
    # fnmatchcase is this test's own reading of the patterns ('*' also crosses '/'), not Claude Code's matcher: it
    # shows that the allow rule misses every denied file and that the nested denies cover nested files as written,
    # not what the tool does with them. What the tool did on 2026-11-23 (a write to one nested path,
    # dev_team/x/.claude/skills/y/SKILL.md, refused) is in demo_video/README.md.
    allow = [a[len("Edit("):-1] for a in _settings()["permissions"]["allow"] if a.startswith("Edit(")]
    for path in ("./demo_scenes/search", "./demo_scenes/logs", "./platform_team/shared_code/hub_env.sh",
                 "./.claude/settings.json", "./.mcp.json", "./pyproject.toml", "./uv.lock", "./CLAUDE.md",
                 "~/.claude/settings.json", "~/.claude.json"):
        assert not [e for e in allow if fnmatchcase(path, e)], path
    assert fnmatchcase("./dev_team/quality_agent/agent.py", allow[0])
    nested = [d[len("Edit("):-1] for d in _settings()["permissions"]["deny"] if d.startswith("Edit(./dev_team/**/")]
    assert nested == ["./dev_team/**/.claude/**", "./dev_team/**/.mcp.json", "./dev_team/**/CLAUDE.md"]
    for path in ("./dev_team/x/.claude/skills/y/SKILL.md", "./dev_team/quality_agent/.claude/settings.json",
                 "./dev_team/x/.mcp.json", "./dev_team/quality_agent/CLAUDE.md"):
        assert [d for d in nested if fnmatchcase(path, d)], path
    for path in ("./dev_team/quality_agent/agent.py", "./dev_team/quality_agent/requirements.txt"):
        assert not [d for d in nested if fnmatchcase(path, d)], path


def test_the_readme_and_the_projects_claude_md_say_what_the_settings_say():
    readme = (VIDEO / "README.md").read_text(encoding="utf-8")
    for rule in ALLOWED + DENIED + ['"disableAutoMode": "disable"', '"defaultMode": "default"']:
        assert f"`{rule}`" in readme, rule
    claude_md = (DEV_PC / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`dev_team/` 아래에만" in claude_md and "개발자가 직접" in claude_md
    for folder in ("`demo_scenes/`", "`platform_team/`", "`.claude/`", "`.mcp.json`", "`pyproject.toml`", "`uv.lock`",
                   "`CLAUDE.md`", "`~/.claude/`", "`~/.claude.json`"):
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
elif args[-2:-1] == ["ls"] and "FAKE_LS" in os.environ:
    sys.stdout.write(os.environ["FAKE_LS"])
else:
    sys.stdout.write(os.environ.get("FAKE_STDOUT", ""))
    if os.environ.get("FAKE_STDERR"):
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
        r = subprocess.run([str(repo / "demo_video/tools/dev_pc/run.sh"), *args], capture_output=True,
                           env=env | extra, timeout=60)
        # decoded here, not with text=True, so that a carriage return run.sh lets through stays one
        return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode(), r.stderr.decode())

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


# text a program in the container chose: a title and a screen clear, colours, a bell, a carriage return, an 8-bit CSI
# (U+009B), a tab, and one long line
CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")                       # every control but tab and newline
CHOSEN = "\x1b]0;title\x07\x1b[2J\x1b[31mred\x1b[0m\ttab\r\x9b1mc1 " + "y" * 400 + "\n"


def test_up_shows_the_containers_listing_without_control_characters_and_cut_short(fake_pc):
    r = fake_pc["run"]("up", FAKE_LS="agent_template\n\x1b[2J\x1b]0;x\x07planted\n" + "z" * 400 + "\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not CONTROLS.search(r.stdout + r.stderr), repr(r.stdout + r.stderr)
    listing = r.stdout.split("(dev_team: ", 1)[1].split("), quality_agent comes with", 1)[0]
    assert "agent_template" in listing and "planted" in listing and listing.endswith(" [cut]")
    assert len(listing) <= 300 + len(" [cut]")


def test_check_shows_the_containers_output_without_control_characters_and_cut_short(fake_pc):
    r = fake_pc["run"]("check", FAKE_STDOUT=CHOSEN, FAKE_STDERR="\x1b[2Jarn:aws:iam::234567890123:role/x\x07 denied")
    out = r.stdout + r.stderr
    assert not CONTROLS.search(out), repr(out)
    assert "red" in out and "\ttab" in out and "[cut]" in out                  # the text stays, the tab too
    assert "234567890123" not in out and "<ACCOUNT>" in out
    assert max(len(line) for line in out.splitlines()) <= 300 + len(" [cut]")


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


def _with_beat(text, at="shot:wide"):
    """The build's SPEC with one caption on the first piece of 00-home instead of its own."""
    import copy
    build = _build()
    spec = copy.deepcopy(build.SPEC)
    spec["clips"]["00-home"][0]["beats"]["ko"] = [{"at": at, "text": text}]
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
    assert (tmp_path / "ok" / "scripts" / "ko" / "00-home.1.json").exists()


def test_a_caption_anchored_to_raw_seconds_stops_the_build(tmp_path, capsys):
    # a caption is anchored to a shot or a note of the take's camlog, so it stays on the event it names
    text = "허브가 신청을 자동으로 심사합니다"
    _refused(_with_beat(text, at=12.5), tmp_path, text)
    err = capsys.readouterr().err
    assert text in err and "raw seconds" in err


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
    spec["clips"]["00-home"][0]["beats"]["ko"] = [{"at": "shot:wide", "text": "허브가 신청을 자동으로 심사합니다"}] * 6
    _refused(spec, tmp_path, "준비")
    assert "준비" in capsys.readouterr().err
    # the budget counts every piece of a stage's takes: 12-make (cut from the 11-find recording) is stage 1
    assert build.stage("12-make") == 1 and build.stage("00-home") == 0 and build.stage("57-back") == 5
    spec = copy.deepcopy(build.SPEC)
    spare = 11 - sum(len(p["beats"]["ko"]) for t in spec["clips"] if build.stage(t) == 1 for p in spec["clips"][t])
    spec["clips"]["12-make"][-1]["beats"]["ko"] += [{"at": "shot:made", "text": "허브가 신청을 자동으로 심사합니다"}] * (spare + 1)
    _refused(spec, tmp_path, "1단계")
    assert "1단계" in capsys.readouterr().err


# the takes of the video, in the order they are recorded (12-make is cut from the 11-find recording)
CLIP_TAKES = ["00-home", "11-find", "12-make", "13-submit", "21-review", "22-works", "23-reject", "24-again",
              "25-approved", "26-answers", "31-logonly", "32-passes", "33-record", "41-enforce", "42-blocked",
              "43-before", "44-attach", "45-after", "51-usage", "52-incident", "53-alarm", "54-stop", "55-neighbours",
              "56-cause", "57-back"]


def test_every_reel_names_only_clips_the_build_defines(tmp_path, capsys):
    build = _build()
    spec = build.SPEC
    names = set(spec["clips"]) | set(spec["cards"]["ko"])
    assert set(spec["reels"]) == {"main", "stage-1", "stage-2", "stage-3", "stage-4", "stage-5"}
    for reel, segments in spec["reels"].items():
        for seg in segments:
            assert seg in names, (reel, seg)
    # every take of the script is a clip of the main reel, in the order the takes are recorded
    main = spec["reels"]["main"]
    assert [n for n in main if n in spec["clips"]] == CLIP_TAKES
    assert main[0] == "card-intro" and main[-2:] == ["card-summary", "card-closing"]
    # a reel that names something the build does not define is refused before anything is written
    import copy
    bad = copy.deepcopy(spec)
    bad["reels"]["stage-2"].append("27-nowhere")
    _refused(bad, tmp_path, "27-nowhere")
    assert "27-nowhere" in capsys.readouterr().err


def test_the_stage_reels_are_the_main_reels_stages_and_stage_1_opens_with_the_preparation():
    build = _build()
    reels = build.SPEC["reels"]
    # the preparation (its chapter card and the home page) opens the main reel and the stage-1 reel
    assert reels["main"][1:3] == ["card-ch0", "00-home"]
    assert reels["stage-1"][:3] == ["card-ch0", "00-home", "card-ch1"]
    # each stage reel is the main reel's run of that stage, so a caption reads the same in every reel
    for n in range(1, 6):
        stage = reels[f"stage-{n}"]
        start = reels["main"].index("card-ch0" if n == 1 else f"card-ch{n}")
        assert reels["main"][start:start + len(stage)] == stage, n
    takes = [t for n in range(1, 6) for t in reels[f"stage-{n}"] if t in build.SPEC["clips"]]
    assert takes == CLIP_TAKES


def test_the_pieces_of_one_take_are_joined_with_hard_cuts():
    build = _build()
    spec = {"clips": {"21-review": [build.piece("21-review", 4.5, 11.5), build.piece("21-review", 30.0, 38.6, speed=4),
                                    build.piece("21-review", 38.6, 60.0)],
                      "22-works": [build.piece("22-works", 11.0, 36.5)]},
            "cards": {"ko": {"card-ch2": {"seconds": 3}}}, "reels": {"r": ["card-ch2", "21-review", "22-works"]}}
    assert build.reel_manifest(spec, "r", "ko") == {"fade": 0.4, "segments": [
        {"file": "cards/ko/card-ch2.mp4"},
        {"file": "clips/ko/21-review.1.mp4", "fade_out": 0},
        {"file": "clips/ko/21-review.2.mp4", "fade_in": 0, "fade_out": 0},
        {"file": "clips/ko/21-review.3.mp4", "fade_in": 0},
        {"file": "clips/ko/22-works.1.mp4"}]}
    # in the main reel every edge between two pieces of one take is a hard cut, and only those
    segments = build.reel_manifest(build.SPEC, "main", "ko")["segments"]
    take = [s["file"].split("/")[-1].rsplit(".", 2)[0] for s in segments]
    for i in range(len(segments) - 1):
        same = take[i] == take[i + 1] and segments[i]["file"].startswith("clips/")
        assert (segments[i].get("fade_out") == 0) == same and (segments[i + 1].get("fade_in") == 0) == same, i
    # interactions play at 1.25 and waits at 4; one window plays slower, to hold a line that is on screen briefly
    speeds = [p["speed"] for pieces in build.SPEC["clips"].values() for p in pieces]
    assert set(speeds) - {1.25, 4} == {0.13} and speeds.count(0.13) == 1


def test_the_main_reel_runs_between_8_and_11_minutes():
    build = _build()
    spec = {"clips": {"t": [build.piece("t", 10.0, 20.0), build.piece("t", 20.0, 60.0, speed=4)]},
            "cards": {"ko": {"c": {"seconds": 3}}}, "reels": {"r": ["c", "t"]}}
    assert build.reel_seconds(spec, "r", "ko") == 3 + 8 + 10
    main = build.reel_seconds(build.SPEC, "main", "ko")
    assert 8 * 60 <= main <= 11 * 60
    # the main reel is the five stage reels (준비 inside stage 1, so counted once) plus the intro, summary and closing
    cards = build.SPEC["cards"]["ko"]
    stages = sum(build.reel_seconds(build.SPEC, f"stage-{n}", "ko") for n in range(1, 6))
    ends = sum(cards[c]["seconds"] for c in ("card-intro", "card-summary", "card-closing"))
    assert main == pytest.approx(stages + ends)


CARDS_OF_THE_SCRIPT = {
    "card-intro": ["AI 에이전트 호스팅 허브 on Amazon Bedrock AgentCore", "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다"],
    "card-ch0": ["준비", "플랫폼팀이 허브를 한 번 만들어 둡니다", "허브 화면의 홈"],
    "card-ch1": ["1단계. 호스팅 신청", "팀은 플랫폼팀 없이 찾고, 만들고, 신청합니다", "Claude Code와 AWS Agent Registry"],
    "card-ch2": ["2단계. 호스팅 심사", "신청이 들어오면 허브가 자동으로 심사합니다", "심사 파이프라인과 AgentCore Runtime"],
    "card-ch3": ["3단계. 전사 정책 시험", "새 전사 정책을 막지 않고 먼저 시험합니다", "Policy in AgentCore의 기록 모드"],
    "card-ch4": ["4단계. 전사 정책 적용", "전사 정책 하나가 모든 에이전트에 걸립니다", "AgentCore Gateway와 커스텀 가드레일"],
    # 경보, not 알람: the hub screen and every caption say 경보, so the card does too
    "card-ch5": ["5단계. 이상 대응", "문제를 일으킨 에이전트 하나만 멈춥니다", "CloudWatch 경보와 AgentCore Runtime"],
    "card-compare": ["가드레일 두 가지", "기본 제공 가드레일과 커스텀 가드레일", "기본 제공은 설정으로 걸고 기록 모드로 먼저 시험합니다",
                     "커스텀은 사내 코드로 막고 민감 정보를 가립니다", "둘 다 게이트웨이에 걸려 모든 에이전트에 적용됩니다"],
    "card-summary": ["정리", "팀은 스스로 올리고, 플랫폼팀은 한 곳에서 관리합니다", "팀은 카탈로그에서 찾고 템플릿으로 만들어 스스로 신청합니다",
                     "허브가 자동으로 심사하고 통과한 것만 올립니다", "전사 정책은 게이트웨이에 한 번 걸면 모두에 적용됩니다",
                     "이상 에이전트 하나만 멈추고 이웃은 계속 답합니다"],
    # one row "AgentCore는 Runtime, Gateway, Policy, Registry, 관측을 줍니다" would be 54 characters: the same words in
    # two rows of at most 45
    "card-closing": ["누가 무엇을 맡나", "AgentCore가 주는 것과 플랫폼팀이 만드는 것", "AgentCore는 Runtime, Gateway, Policy를 줍니다",
                     "AgentCore는 Registry와 관측도 줍니다", "플랫폼팀은 심사 파이프라인과 운영 명령, 허브 화면을 만듭니다"],
}
SECONDS_OF_THE_SCRIPT = {"card-intro": 4, "card-compare": 8, "card-summary": 9, "card-closing": 7}


def test_the_cards_of_the_script_pass_the_rules(tmp_path):
    build = _build()
    cards = build.SPEC["cards"]["ko"]
    assert {name: build.card_texts(card) for name, card in cards.items()} == CARDS_OF_THE_SCRIPT
    assert {n: cards[n]["seconds"] for n in SECONDS_OF_THE_SCRIPT} == SECONDS_OF_THE_SCRIPT
    # the whole build file passes its own rules: these cards, and every caption of every piece
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
    assert {"file": "clips/ko/00-home.1.mp4"} in [{"file": s["file"]} for s in manifest["segments"]]
    # each piece's script for the plugin: its window, its speed, its captions (the fields of a silent caption: a
    # narration and its boxes stay out), and no title (the cards carry it)
    script = json.loads((tmp_path / "out" / "scripts" / "ko" / "00-home.1.json").read_text(encoding="utf-8"))
    home = build.SPEC["clips"]["00-home"][0]
    silent = [{k: v for k, v in b.items() if k in ("at", "text", "offset", "dur", "pos")} for b in home["beats"]["ko"]]
    assert script == {"start": home["start"], "end": home["end"], "speed": 1.25, "beats": silent}
    assert script["beats"] and all(isinstance(b["at"], str) for b in script["beats"])


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


def test_the_narrated_build_says_it_needs_demo_video_1_4_0_when_the_plugin_has_no_check_demo_py(tmp_path):
    # demo-video 1.3.0 has edit_demo.py and make_cards.py and no check_demo.py: the line names the version the narrated
    # build needs, so that an older plugin does not read as a wrong folder
    env = {k: v for k, v in os.environ.items() if k != "DEMO_VIDEO_PLUGIN"}
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    for f in ("edit_demo.py", "make_cards.py"):
        (plugin / f).write_text("raise SystemExit(9)\n")

    def voice(**extra):
        return subprocess.run([sys.executable, str(BUILD), "--voice", "--out", str(tmp_path / "out")],
                              capture_output=True, text=True, env=env | extra, timeout=60)
    r = voice(DEMO_VIDEO_PLUGIN=str(plugin))
    assert r.returncode == 2 and len(r.stderr.splitlines()) == 1, r.stderr
    assert "check_demo.py" in r.stderr and "the narrated build needs demo-video 1.4.0 or later" in r.stderr
    assert "https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video" in r.stderr
    # no folder, or a folder without another of the scripts: the line names the folder and its three scripts
    (plugin / "check_demo.py").write_text("raise SystemExit(9)\n")
    (plugin / "make_cards.py").unlink()
    for r in (voice(DEMO_VIDEO_PLUGIN=str(plugin)), voice()):
        assert r.returncode == 2 and "1.4.0" not in r.stderr, r.stderr
        assert ("DEMO_VIDEO_PLUGIN must name the scripts folder of the demo-video plugin (edit_demo.py, make_cards.py, "
                "check_demo.py)") in r.stderr
    assert not (tmp_path / "out").exists()


def test_a_clip_with_no_beats_is_cut_without_captions(tmp_path):
    # the plugin's clip falls back to the camera's shot labels when a script has no beats: those are notes for the
    # person who records, never captions
    build = _build()
    cmd = build.clip_command(Path("/plugin"), "21-review.2", build.piece("21-review", 30.0, 38.6, speed=4), "ko",
                             tmp_path)
    assert "--no-captions" in cmd and "--title" not in cmd
    assert cmd[3] == str(tmp_path / "raw" / "21-review.webm")
    assert cmd[cmd.index("--out") + 1] == str(tmp_path / "clips" / "ko" / "21-review.2.mp4")
    cmd = build.clip_command(Path("/plugin"), "00-home.1", build.SPEC["clips"]["00-home"][0], "ko", tmp_path)
    assert "--no-captions" not in cmd and "--title" not in cmd


CAMLOG = {"log": [{"t": 3.9, "kind": "shot", "key": "wide"}, {"t": 14.91, "kind": "shot", "key": "flow1"},
                  {"t": 20.0, "kind": "asked"}, {"t": 41.93, "kind": "shot", "key": "end"}]}
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


@pytest.fixture(scope="module")
def take_45s(tmp_path_factory):
    """A real webm of 45 s (black, 64x36), so the build can measure the take as it measures a recorded one."""
    path = tmp_path_factory.mktemp("take") / "take.webm"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=5:d=45",
                    "-c:v", "libvpx", "-deadline", "realtime", "-b:v", "20k", str(path)], check=True, timeout=60)
    return path


def _cut(tmp_path, monkeypatch, take, pieces):
    """build.run on one take (00-home, its camlog CAMLOG, its video the 45 s take) with a stand-in plugin that only
    notes that it was called; returns the exit code (None when the build went through) and whether anything was cut."""
    build = _build()
    import copy
    spec = copy.deepcopy(build.SPEC)
    spec["clips"] = {"00-home": pieces}
    spec["reels"] = {"main": ["card-intro", "00-home"]}
    out = tmp_path / "out"
    (out / "raw").mkdir(parents=True)
    shutil.copy(take, out / "raw" / "00-home.webm")
    (out / "raw" / "00-home.camlog.json").write_text(json.dumps(CAMLOG))
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    for f in ("edit_demo.py", "make_cards.py"):
        (plugin / f).write_text("import pathlib, sys\npathlib.Path(sys.argv[0]).with_suffix('.called').touch()\n")
    monkeypatch.setenv("DEMO_VIDEO_PLUGIN", str(plugin))
    try:
        build.run(spec, lang="ko", out=out)
        code = None
    except SystemExit as stop:
        code = stop.code
    return code, bool(list(plugin.glob("*.called")))


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
@pytest.mark.parametrize("at, offset, says", [
    ("shot:flow1", 0, "outside"),            # 14.91 s lies after the piece's window 3.5..12
    ("shot:wide", 0, None),                  # 3.9 s: inside
    ("shot:wide", 7.0, "outside"),           # 10.9 s: inside the window, but less than 2 s of the piece is left
    ("asked#2", 0, "does not hold"),         # the camlog has one note asked
    ("shot:nowhere", 0, "does not hold")])
def test_a_caption_outside_its_piece_or_off_the_camlog_stops_the_build_before_anything_is_cut(
        tmp_path, capsys, monkeypatch, take_45s, at, offset, says):
    build = _build()
    text = "허브 화면에서 흐름 1을 봅니다"
    code, cut = _cut(tmp_path, monkeypatch, take_45s,
                     [build.piece("00-home", 3.5, 12.0, ko=[build.beat(at, text, offset=offset)])])
    if says is None:
        assert code is None and cut
        return
    err = capsys.readouterr().err
    assert code == 2 and not cut                              # nothing was cut
    assert text in err and says in err and "00-home.1" in err


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
@pytest.mark.parametrize("start, end, dur, says", [
    (12.0, 12.0, None, "does not start before it ends"),     # an empty window
    (20.0, 12.0, None, "does not start before it ends"),
    (3.5, 50.0, None, "beyond the take"),                    # the take is 45 s long
    (3.5, 41.5, 10.0, "runs into the next caption"),         # 0.32 s + 10 s passes the next caption at 9.13 s
    (3.5, 41.5, 8.0, None),                                  # 8 s ends before it
    (3.5, 45.0, None, None)])                                # up to the take's end
def test_a_piece_beyond_its_take_or_a_caption_running_into_the_next_stops_the_build_before_anything_is_cut(
        tmp_path, capsys, monkeypatch, take_45s, start, end, dur, says):
    build = _build()
    first = build.beat("shot:wide", "허브 화면 한 곳에서 허브를 봅니다", **({} if dur is None else {"dur": dur}))
    second = build.beat("shot:flow1", "흐름 1은 허브가 심사하는 길입니다")
    beats = [first, second] if end > 17 else []
    code, cut = _cut(tmp_path, monkeypatch, take_45s, [build.piece("00-home", start, end, ko=beats)])
    if says is None:
        assert code is None and cut
        return
    err = capsys.readouterr().err
    assert code == 2 and not cut and says in err and "00-home.1" in err


# ------------------------------------------------------------------ the voiced build: narrations, boxes, held captions

# sha256 of what `build.py --check` writes (every file under scripts/ko/, cards/ko/cards.json and reels/*.json).
# Set anew on 2026-11-24, when the owner changed words in nine captions (판 -> 버전, 저절로 -> 자동으로,
# 짚습니다 -> 찾습니다); nothing else of the silent build changed. The old value pinned the files the six silent reels of
# 2026-11-23 were cut from; those reels, with their clips, scripts and cards, are kept at demo_video/out/silent-2026-11-23/.
SILENT_DIGEST = "3414a11e78fa6eff0f3613db8c439525e084a88c02e36b1a33e480164663d45e"
SILENT_DIGEST_2026_11_23 = "21e5469e3fee886ddb56a5ebeab6dbe448c3c1a5f53fe19de772652afce31e47"
# the captions the owner's words changed on 2026-11-24: silent piece -> (caption of 2026-11-23, caption now)
NEW_WORDS_2026_11_24 = {
    "13-submit.2": ("quality_agent의 v1-vulnerable 판도 승인 대기가 됩니다", "quality_agent의 v1-vulnerable 버전도 승인 대기가 됩니다"),
    "21-review.1": ("신청이 들어오자 두 에이전트의 호스팅 심사가 저절로 시작됩니다", "신청이 들어오자 두 에이전트의 호스팅 심사가 자동으로 시작됩니다"),
    "24-again.1": ("개발자는 jinja2를 뺀 고친 판을 다시 신청합니다", "개발자는 jinja2를 뺀 고친 버전을 다시 신청합니다"),
    "25-approved.4": ("고친 판도 일곱 단계를 모두 통과해 승인이 됩니다", "고친 버전도 일곱 단계를 모두 통과해 승인이 됩니다"),
    "52-incident.1": ("개발자가 quality_agent의 새 판 v2-loop를 신청합니다", "개발자가 quality_agent의 새 버전 v2-loop를 신청합니다"),
    "52-incident.2": ("이 판도 일곱 단계 심사를 모두 통과해 승인이 됩니다", "이 버전도 일곱 단계 심사를 모두 통과해 승인이 됩니다"),
    "56-cause.3": ("Claude Code는 로그와 코드를 읽고 재시도에 횟수 제한이 없다고 짚습니다",
                   "Claude Code는 로그와 코드에서 재시도 횟수 제한이 없다는 원인을 찾습니다"),
    "57-back.1": ("개발자는 원인을 고친 판을 다시 신청합니다", "개발자는 원인을 고친 버전을 다시 신청합니다"),
    "57-back.2": ("에이전트가 멈춘 동안에도 고친 판의 심사는 끝까지 통과합니다", "에이전트가 멈춘 동안에도 고친 버전의 심사는 끝까지 통과합니다"),
}


def _digest(out: Path) -> str:
    """sha256 over the silent build's script files, cards.json and reel manifests, in sorted order of their paths
    relative to out: per file the path, a NUL byte, the file's bytes, a NUL byte."""
    import hashlib
    files = [*(out / "scripts" / "ko").rglob("*"), out / "cards" / "ko" / "cards.json", *(out / "reels").glob("*.json")]
    h = hashlib.sha256()
    for f in sorted((f for f in files if f.is_file()), key=lambda f: f.relative_to(out).as_posix()):
        h.update(f.relative_to(out).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def test_the_silent_build_writes_the_files_pinned_on_2026_11_24(tmp_path):
    build = _build()
    build.run(build.SPEC, out=tmp_path, check_only=True)
    assert _digest(tmp_path) == SILENT_DIGEST


def test_the_silent_build_differs_from_the_reels_of_2026_11_23_only_in_the_owners_new_words(tmp_path):
    # with the nine captions of 2026-11-23 put back, the silent build writes byte for byte the files those reels were cut
    # from: no time, position, cut, card or other text changed with the words
    import copy
    build = _build()
    spec = copy.deepcopy(build.SPEC)
    for take, pieces in spec["clips"].items():
        for name, part in zip(build.piece_names(take, pieces), pieces):
            if name in NEW_WORDS_2026_11_24:
                old, now = NEW_WORDS_2026_11_24[name]
                hits = [b for b in part["beats"]["ko"] if b["text"] == now]
                assert len(hits) == 1, name
                hits[0]["text"] = old
    build.run(spec, out=tmp_path, check_only=True)
    assert _digest(tmp_path) == SILENT_DIGEST_2026_11_23


def test_the_silent_scripts_carry_no_voice_fields(tmp_path):
    # a narration, a box, what it points at, its delay and length, a voice start on every caption, a narration on every
    # card:
    # the silent build still writes exactly what it wrote before
    import copy
    build = _build()
    spec = copy.deepcopy(build.SPEC)
    for pieces in spec["clips"].values():
        for p in pieces:
            for b in p["beats"]["ko"]:
                b.update(say="허브가 신청을 심사합니다.", box=[100, 200, 300, 120], what=["심사 표"], box_delay=0.5,
                         box_dur=2.0, voice_at=1.0, ends_early=True)
    for card in spec["cards"]["ko"].values():
        card["say"] = "허브를 소개합니다."
    build.run(spec, out=tmp_path, check_only=True)
    assert _digest(tmp_path) == SILENT_DIGEST
    # a beat with every field: the silent script keeps the five of a silent caption
    part = build.piece("00-home", 3.5, 20.0, ko=[build.beat("shot:wide", "허브 화면을 봅니다", offset=0.5, dur=4.0, pos="top",
                                                             say="허브 화면입니다.", box=[100, 200, 300, 120],
                                                             what=["허브 화면"], box_delay=0.5, box_dur=2.0,
                                                             voice_at=1.0, ends_early=True)])
    assert build.clip_script(part, "ko")["beats"] == [{"at": "shot:wide", "text": "허브 화면을 봅니다", "offset": 0.5,
                                                       "dur": 4.0, "pos": "top"}]


def test_a_piece_with_three_captions_becomes_three_pieces_cut_before_each_anchor():
    import copy
    build = _build()
    log = CAMLOG["log"]                                            # wide 3.9, flow1 14.91, asked 20.0
    beats = [build.beat("asked", "셋째 자막입니다", offset=0.5),     # written out of order: the pieces follow the anchors
             build.beat("shot:wide", "첫째 자막입니다"), build.beat("shot:flow1", "둘째 자막입니다", say="둘째 자막입니다.")]
    part = build.piece("11-find", 3.5, 41.5, ko=beats)
    pieces = build.split_piece(part, "ko", log)
    assert [p["beats"]["ko"] for p in pieces] == [[beats[1]], [beats[2]], [beats[0]]]          # one caption each
    assert pieces[0]["start"] == 3.5 and pieces[-1]["end"] == 41.5                           # the piece's two ends
    assert [p["end"] for p in pieces[:-1]] == [p["start"] for p in pieces[1:]]               # no gap, no overlap
    assert pieces[1]["start"] == pytest.approx(14.91 - 0.2)                                  # 0.2 s before its anchor
    assert pieces[2]["start"] == pytest.approx(20.0 + 0.5 - 0.2)                             # the anchor with its offset
    assert all(p["raw"] == "11-find" and p["speed"] == 1.25 for p in pieces)
    one, none = build.piece("11-find", 3.5, 12.0, ko=[beats[1]]), build.piece("11-find", 3.5, 9.0)
    assert build.split_piece(one, "ko", log) == [one] and build.split_piece(none, "ko", []) == [none]   # as they are
    # the whole spec: the pieces of a take are numbered anew, the camlogs are those of the raw takes (12-make is cut
    # from the 11-find recording), and nothing else changes
    wait = build.piece("11-find", 41.5, 44.0, speed=4)
    spec = {"clips": {"12-make": [one, part, wait]}, "cards": {"ko": {"card-ch1": {"seconds": 3, "say": "일단계입니다."}}},
            "reels": {"r": ["card-ch1", "12-make"]}}
    before = copy.deepcopy(spec)
    v = build.voiced(spec, "ko", {"11-find": log})
    assert spec == before
    assert v["clips"]["12-make"] == [one, *pieces, wait]
    assert build.piece_names("12-make", v["clips"]["12-make"]) == [f"12-make.{n}" for n in range(1, 6)]
    assert v["cards"] == spec["cards"] and v["reels"] == spec["reels"]


def test_a_caption_that_ends_early_has_its_piece_cut_where_it_ended_in_the_silent_video():
    # a narrated caption is held to its piece's end; with "ends_early" its piece ends where the caption ended in the
    # silent video, and the rest of the take's window plays on as a piece without a caption, the voice running on
    build = _build()
    log = CAMLOG["log"]                                            # wide 3.9, flow1 14.91
    early = build.beat("shot:wide", "허브 화면을 봅니다", dur=4.0, ends_early=True, say="허브 화면입니다.",
                       box=[100, 200, 300, 120], what=["허브 화면"])
    later = build.beat("shot:flow1", "흐름 1은 허브가 심사하는 길입니다", say="흐름 일입니다.")
    spec = {"clips": {"00-home": [build.piece("00-home", 3.5, 41.5, ko=[early, later])]}, "cards": {"ko": {}},
            "reels": {"r": ["00-home"]}}
    v = build.voiced(spec, "ko", {"00-home": log})
    pieces = v["clips"]["00-home"]
    # the caption ended at its start plus dur in the finished piece: 3.9 + 4.0 * 1.25 = 8.9 s of the take
    assert [(p["start"], p["end"]) for p in pieces] == [(3.5, 8.9), (8.9, 14.71), (14.71, 41.5)]
    assert [p["beats"]["ko"] for p in pieces] == [[early], [], [later]]
    assert all(p["raw"] == "00-home" and p["speed"] == 1.25 for p in pieces)
    assert build.voiced_script(pieces[0], "ko")["beats"][0]["hold"] is True              # held to its earlier end
    assert build.voiced_script(pieces[1], "ko")["beats"] == []
    # the three pieces meet in hard cuts and share the take's group: the voice runs on over the captionless rest
    m = build.voiced_manifest(v, "r", "ko", build.voice_starts(v, "ko", {"00-home": log}))
    assert [(s["file"], s["group"], s.get("fade_in"), s.get("fade_out"), s.get("voice_at")) for s in m["segments"]] == [
        ("clips/ko-voice/00-home.1.mp4", "00-home", None, 0, 0.62), ("clips/ko-voice/00-home.2.mp4", "00-home", 0, 0, None),
        ("clips/ko-voice/00-home.3.mp4", "00-home", 0, None, 0.46)]
    # the plugin shows a caption 1.5 s at least, so a shorter dur ends it there
    assert build.early_end({**early, "dur": 1.0}, pieces[0], log) == pytest.approx(3.9 + 1.5 * 1.25)
    # without the switch, or with it false, the piece is as before
    for off in ({k: x for k, x in early.items() if k != "ends_early"}, {**early, "ends_early": False}):
        plain = {**spec, "clips": {"00-home": [build.piece("00-home", 3.5, 41.5, ko=[off, later])]}}
        assert [(p["start"], p["end"]) for p in build.voiced(plain, "ko", {"00-home": log})["clips"]["00-home"]] == [
            (3.5, 14.71), (14.71, 41.5)]


def test_of_the_captions_with_dur_only_21_review_3_ends_early():
    # 21-review.3's caption (the failed Scan) would stay over release_review's page once the camera moves on at
    # release_card; the other three captions with "dur" read true to their pieces' ends and stay held
    build = _build()
    with_dur = {f"{name}: {b['text']}": b.get("ends_early", False) for take, pieces in build.SPEC["clips"].items()
                for name, part in zip(build.piece_names(take, pieces), pieces) for b in part["beats"]["ko"] if "dur" in b}
    assert with_dur == {"12-make.2: Claude Code는 셸 명령을 실행하기 전에 개발자에게 묻습니다": False,
                        "21-review.3: quality_agent의 심사는 의존성 검사 Scan에서 실패해 멈춥니다": True,
                        "51-usage.1: 플랫폼팀은 에이전트마다 호출과 세션 수를 한 화면에서 봅니다": False,
                        "54-stop.3: 멈추기는 그 에이전트의 진입을 정책으로 막고 세션을 끝냅니다": False}
    assert [b for pieces in build.SPEC["clips"].values() for part in pieces for b in part["beats"]["ko"]
            if "ends_early" in b and "dur" not in b] == []


def test_a_voiced_caption_is_held_and_its_voice_starts_0_3_s_after_it():
    build = _build()
    said = build.beat("shot:flow1", "흐름 1은 허브가 심사하는 길입니다", offset=0.4, say="흐름 일은 허브가 심사하는 길입니다.",
                      box=[100, 200, 300, 120], what=["흐름 1의 설명"], box_delay=0.8, box_dur=3.0)
    plain = build.beat("shot:wide", "허브 화면을 봅니다", dur=3.0)
    part_said, part_plain = build.piece("00-home", 14.0, 30.0, ko=[said]), build.piece("00-home", 3.5, 14.0, ko=[plain])
    assert build.voiced_script(part_said, "ko") == {"start": 14.0, "end": 30.0, "speed": 1.25, "beats": [
        {"at": "shot:flow1", "text": "흐름 1은 허브가 심사하는 길입니다", "offset": 0.4, "box": [100, 200, 300, 120],
         "box_delay": 0.8, "box_dur": 3.0, "hold": True}]}
    assert build.voiced_script(part_plain, "ko") == build.clip_script(part_plain, "ko")     # no narration: as today
    spec = {"clips": {"00-home": [part_plain, part_said]},
            "cards": {"ko": {"card-ch0": {"seconds": 3, "say": "준비입니다."}, "card-intro": {"seconds": 4}}},
            "reels": {"r": ["card-intro", "card-ch0", "00-home"]}}
    logs = {"00-home": CAMLOG["log"]}
    assert build.voice_starts(spec, "ko", logs) == pytest.approx({"card-ch0": 0.3,
                                                                  "00-home.2": (14.91 + 0.4 - 14.0) / 1.25 + 0.3})
    said["voice_at"] = 2.5                                         # given on the beat, it replaces the computed start
    assert build.voice_starts(spec, "ko", logs)["00-home.2"] == 2.5


def test_cards_are_picture_segments_and_pieces_of_a_take_share_a_group():
    build = _build()
    # the build gives the plugin its thresholds: the gap between voices, the tail, the loudness and the audit's tolerance
    assert (build.VOICE_GAP, build.VOICE_TAIL, build.LOUDNESS, build.VOICE_TOLERANCE) == (0.6, 1.0, -16.0, 0.25)
    said = build.beat("shot:list", "신청이 들어오자 심사가 시작됩니다", say="신청이 들어오자 심사가 시작됩니다.")
    plain = build.beat("shot:quality", "심사는 Scan에서 멈춥니다")
    spec = {"clips": {"21-review": [build.piece("21-review", 4.5, 11.5, ko=[said]),
                                    build.piece("21-review", 30.0, 38.6, speed=4),
                                    build.piece("21-review", 38.6, 60.0, ko=[plain])],
                      "22-works": [build.piece("22-works", 11.0, 36.5)]},
            "cards": {"ko": {"card-ch2": {"seconds": 3}}}, "reels": {"r": ["card-ch2", "21-review", "22-works"]}}
    at = {"card-ch2": 0.3, "21-review.1": 0.62}
    # a captioned piece without a narration (21-review.3) has a group of its own: the voice of 21-review.1 may run on
    # over the wait 21-review.2, never over another caption
    assert build.voiced_manifest(spec, "r", "ko", at) == {"fade": 0.4, "voice_gap": 0.6, "voice_tail": 1.0,
                                                          "loudness": -16.0, "segments": [
        {"image": "cards/ko/card-ch2.png", "seconds": 3, "voice": "voice/ko/card-ch2.mp3", "voice_at": 0.3},
        {"file": "clips/ko-voice/21-review.1.mp4", "group": "21-review", "fade_out": 0,
         "voice": "voice/ko/21-review.1.mp3", "voice_at": 0.62},
        {"file": "clips/ko-voice/21-review.2.mp4", "group": "21-review", "fade_in": 0, "fade_out": 0},
        {"file": "clips/ko-voice/21-review.3.mp4", "group": "21-review.3", "fade_in": 0},
        {"file": "clips/ko-voice/22-works.1.mp4", "group": "22-works"}]}


def _unsaid(build):
    """The build's SPEC with every narration taken out, so that a test speaks only the narrations it writes (with the
    readings it gives) on the reels it builds; an early end goes with its narration (only a narrated caption has one)."""
    import copy
    spec = copy.deepcopy(build.SPEC)
    for card in spec["cards"]["ko"].values():
        card.pop("say", None)
    for pieces in spec["clips"].values():
        for part in pieces:
            for b in part["beats"]["ko"]:
                b.pop("say", None)
                b.pop("ends_early", None)
    return spec


def _narrate(build, say, **opts):
    """The build's SPEC without its narrations, with one narration (and other beat fields) on the first caption of
    00-home."""
    spec = _unsaid(build)
    spec["clips"]["00-home"][0]["beats"]["ko"][0].update(say=say, **opts)
    return spec


def _voice_refused(build, spec, tmp_path):
    """The voiced build stops before it writes anything (exit 2)."""
    with pytest.raises(SystemExit) as stop:
        build.run_voice(spec, "ko", tmp_path / "out", check_only=True)
    assert stop.value.code == 2 and not (tmp_path / "out").exists()


CAPTION = "00-home.1: '허브 화면 한 곳에서 호스팅된 에이전트와 공유 도구를 봅니다'"     # how a problem names the first caption
BOX_FIELDS = ("box", "what", "box_delay", "box_dur")


def _first_caption_unboxed(build):
    """The build's SPEC, and its first caption (00-home) with its own box and what it points at taken away, so that a
    test gives that caption only the box fields it checks."""
    import copy
    spec = copy.deepcopy(build.SPEC)
    beat = spec["clips"]["00-home"][0]["beats"]["ko"][0]
    for field in BOX_FIELDS:
        beat.pop(field, None)
    return spec, beat


def test_a_narration_with_a_latin_letter_or_digit_after_the_readings_stops_the_build(tmp_path, capsys, monkeypatch):
    build = _build()
    monkeypatch.setitem(build.READINGS, "ko", {"Step": "스텝", "Step Functions": "스텝 펑션스", "403": "사공삼",
                                               "release_review": "릴리스 리뷰"})
    # the longest name is read first, as the plugin's voice step reads it ("스텝 Functions" would be left otherwise)
    assert build.narration_problems(_narrate(build, "release_review는 Step Functions로 심사해 403을 받습니다."), "ko") == []
    bad = "release_review는 v2-loop로 403을 받습니다."
    found = build.narration_problems(_narrate(build, bad), "ko")
    assert len(found) == 1 and found[0].startswith(CAPTION)
    assert repr(bad) in found[0] and "'v', '2', 'loop'" in found[0] and "릴리스 리뷰는 v2-loop로 사공삼을 받습니다." in found[0]
    _voice_refused(build, _narrate(build, bad), tmp_path)
    err = capsys.readouterr().err
    assert repr(bad) in err and "'loop'" in err
    # a card's narration: the problem names the card
    spec = _unsaid(build)
    spec["cards"]["ko"]["card-closing"]["say"] = "AgentCore가 런타임을 줍니다."
    assert build.narration_problems(spec, "ko") == [
        "card-closing: the narration 'AgentCore가 런타임을 줍니다.' still holds 'AgentCore' after the readings "
        "(spoken: 'AgentCore가 런타임을 줍니다.'): give it a reading in READINGS['ko'] or write it in Hangul"]


@pytest.mark.parametrize("say", ["", "  ", "허브가 신청을 심사한다.", "허브가 심사합니다. 그리고 올린다", "허브가 심사할까요?",
                                 "허브가 심사합니다!", "허브가 심사합니다.그리고 올린다."])
def test_a_narration_that_is_not_hamnida_style_stops_the_build(tmp_path, capsys, say):
    # sentences that end in 니다. (the last may leave out its full stop); the 45 characters of a caption do not apply
    build = _build()
    found = build.narration_problems(_narrate(build, say), "ko")
    assert len(found) == 1 and found[0].startswith(CAPTION), found
    assert ("empty" in found[0]) if not say.strip() else ("니다." in found[0] and repr(say) in found[0])
    _voice_refused(build, _narrate(build, say), tmp_path)
    assert found[0] in capsys.readouterr().err
    for ok in ("허브가 심사합니다.", "허브가 심사합니다. 통과한 것만 올립니다", "팀이 신청하면 허브가 일곱 단계로 심사하고, 모든 단계를 "
               "통과한 버전만 승인합니다. 승인된 버전은 카탈로그에 오르고 에이전트 게이트웨이로 부를 수 있습니다."):
        assert build.narration_problems(_narrate(build, ok), "ko") == [], ok


@pytest.mark.parametrize("bad", ["—", "·", "→"])
def test_a_narration_with_a_dash_dot_or_arrow_stops_the_build(bad):
    build = _build()
    say = f"팀이 신청하면 {bad} 허브가 심사합니다."
    found = build.narration_problems(_narrate(build, say), "ko")
    assert len(found) == 1 and found[0].startswith(CAPTION) and repr(say) in found[0] and "holds a" in found[0]


@pytest.mark.parametrize("box, what, says", [
    ([100, 200, 300, 120], None, 'a box without "what"'),
    ("shot:wide", [], 'a box without "what"'),
    ([[100, 200, 300, 120], [500, 200, 300, 120]], ["심사 표"], '2 box(es) but 1 phrase(s) in "what"'),
    (None, ["심사 표"], '"what" on a caption without a box'),
    ([100, 200, 300, 120], "심사 표", '"what" must be a list of short phrases'),
    ([100, 200, 300, 120], [""], '"what" must be a list of short phrases'),
    ([100, 200, 300, 120], ["심사 표"], None),
    ([[100, 200, 300, 120], [500, 200, 300, 120]], ["심사 표", "승인 줄"], None),
    ("mark:row", ["승인 줄"], None)])
def test_a_box_without_what_stops_the_build(tmp_path, capsys, box, what, says):
    # each box says in a short phrase what it points at, for the review page; a caption may have a box and no narration
    build = _build()
    spec, beat = _first_caption_unboxed(build)
    beat.update({k: v for k, v in (("box", box), ("what", what)) if v is not None})
    found = build.narration_problems(spec, "ko")
    if says is None:
        assert found == []
        return
    assert len(found) == 1 and found[0].startswith(CAPTION) and says in found[0], found
    _voice_refused(build, spec, tmp_path)
    assert says in capsys.readouterr().err


def test_a_narration_no_reel_plays_stops_the_build(tmp_path):
    build = _build()
    spec = _narrate(build, "허브 화면의 홈입니다.")
    spec["cards"]["ko"]["card-ch0"]["say"] = "준비입니다."
    assert build.narration_problems(spec, "ko") == []
    for segments in spec["reels"].values():
        segments[:] = [s for s in segments if s not in ("00-home", "card-ch0")]
    assert build.narration_problems(spec, "ko") == ["card-ch0: a narration on a card that no reel uses",
                                                    f"{CAPTION}: a narration on a piece that no reel uses"]
    _voice_refused(build, spec, tmp_path)


def test_every_card_and_caption_of_the_reels_has_a_narration():
    # the narrated reels speak over every card and every caption they show, and every narration keeps the rules
    build = _build()
    used = build.used_names(build.SPEC)
    cards = build.SPEC["cards"]["ko"]
    unsaid = [name for name, card in cards.items() if name in used and not str(card.get("say") or "").strip()]
    unsaid += [f"{name}: {b['text']!r}" for take, pieces in build.SPEC["clips"].items() if take in used
               for name, part in zip(build.piece_names(take, pieces), pieces)
               for b in part["beats"]["ko"] if not str(b.get("say") or "").strip()]
    assert unsaid == []
    assert build.narration_problems(build.SPEC, "ko") == []


# The plugin's caption box (edit_demo.py: one line of 34 px text at y 930, or at y 120 with "pos": "top", inside an
# 18 px border): a highlight box, with its 2 px dark line outside the 8 px red border, stays out of it.
CAPTION_BAND = {"bottom": (912, 992), "top": (102, 182)}
BORDER, OUTLINE, AIR = 8, 2, 6          # the red border, the dark line outside it, the least air around the thing


def _boxes(build):
    """(silent piece, caption) for every caption of the build's SPEC that has a box."""
    return [(name, b) for take, pieces in build.SPEC["clips"].items()
            for name, part in zip(build.piece_names(take, pieces), pieces) for b in part["beats"]["ko"] if "box" in b]


def test_the_narrations_that_point_at_one_part_of_the_screen_carry_25_to_40_boxes():
    # a box goes where a narration points at one part of the screen, on a narrated caption (it is held with it); each
    # box names what it points at in one short phrase (not a sentence) for the review page
    build = _build()
    boxed = _boxes(build)
    assert 25 <= sum(build.box_count(b["box"]) for _, b in boxed) <= 40
    assert [f"{name}: {b['text']}" for name, b in boxed if not b.get("say")] == []
    phrases = [w for _, b in boxed for w in b["what"]]
    assert [w for w in phrases if len(w) > 20 or w.rstrip(".").endswith("니다")] == []
    assert build.narration_problems(build.SPEC, "ko") == []


def test_every_box_lies_in_the_frame_clear_of_its_caption_and_shows_long_enough_to_be_found():
    build = _build()
    for name, b in _boxes(build):
        rects = b["box"] if isinstance(b["box"][0], list) else [b["box"]]
        top, bottom = CAPTION_BAND[b.get("pos", "bottom")]
        for rect in rects:
            x, y, w, h = rect
            assert all(type(v) is int for v in rect), (name, rect)                 # frame pixels, as placed
            assert x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080, (name, rect)
            assert min(w, h) > 2 * (BORDER + AIR), (name, rect)                    # room for the thing inside
            assert y + h + OUTLINE <= top or y - OUTLINE >= bottom, (name, rect, b.get("pos", "bottom"))
        # a box ended before a camera move shows at least 2.5 s, or a viewer cannot find it; 12-make.2's dialog
        # shows only 2.46 s after the camera stops, and its box fills that room (the next test)
        assert b.get("box_dur", 2.5) >= (2.41 if name == "12-make.2" else 2.5), (name, b["box_dur"])


def test_the_box_on_claude_codes_question_shows_from_the_cameras_stop_until_before_the_dialog_closes():
    # 12-make.2: the shot ask5 is at 71.27 s of the take (camlog of 11-find) and the plugin's camera check counts the
    # move to it until 71.27 + 1.4 = 72.67 s; the No closes the dialog after 75.76 s (seen on the frames: the dialog
    # is on the clip's frame at 75.75 s of the take and closed at 75.79 s)
    build = _build()
    [(part, b)] = [(part, b) for take, pieces in build.SPEC["clips"].items()
                   for name, part in zip(build.piece_names(take, pieces), pieces) for b in part["beats"]["ko"]
                   if name == "12-make.2" and "box" in b]
    assert (b["box_delay"], b["box_dur"]) == (1.12, 2.41)
    begins = build.caption_start(b, part, [{"t": 71.27, "kind": "shot", "key": "ask5"}]) + b["box_delay"]
    shows = (part["start"] + begins * part["speed"], part["start"] + (begins + b["box_dur"]) * part["speed"])
    assert shows[0] >= 71.27 + build.CAMERA_MOVE - 1e-6 and shows[1] < 75.76, shows


# A stand-in for the plugin's scripts (edit_demo.py, make_cards.py, check_demo.py): each call is noted in calls.jsonl
# beside it, and the folder it ran in in cwd.jsonl (a line each, in the same order); it writes small files at the paths
# it is given, of the shapes the build and its next step read. STAND_IN_FAIL="<step>:<a word of its arguments>" (the
# step: make_cards.py or the first word of the command) makes the first matching call fail as the plugin fails: one
# line on stderr, exit 1.
STAND_IN_PLUGIN = r'''
import json, os, pathlib, sys
me, args = pathlib.Path(sys.argv[0]), sys.argv[1:]
with (me.parent / "calls.jsonl").open("a") as f:
    f.write(json.dumps([me.name, *args]) + "\n")
with (me.parent / "cwd.jsonl").open("a") as f:
    f.write(json.dumps(os.getcwd()) + "\n")
fail, _, on = os.environ.get("STAND_IN_FAIL", "").partition(":")
if fail and fail in (me.name, args[0]) and on in " ".join(args):
    print(f"stand-in: {fail} failed", file=sys.stderr)
    raise SystemExit(1)
def opt(name):
    return pathlib.Path(args[args.index(name) + 1])
def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
if me.name == "make_cards.py":
    for name in json.loads(pathlib.Path(args[0]).read_text()):
        put(opt("--out") / f"{name}.png", "card\n")
        put(opt("--out") / f"{name}.mp4", "card\n")
elif args[0] == "voice":
    lines = json.loads(pathlib.Path(args[1]).read_text())
    for name in lines:
        put(opt("--out") / f"{name}.mp3", "voice\n")
    put(opt("--out") / "voice.json", json.dumps({n: {"file": f"{n}.mp3", "seconds": 5.0, "spoken": t, "key": "k"}
                                                 for n, t in lines.items()}))
elif args[0] in ("clip", "reel"):
    put(opt("--out"), args[0] + "\n")
    if args[0] == "reel":
        put(opt("--out").with_suffix(".voice.json"), json.dumps({"segments": [], "voices": [], "warnings": []}))
elif args[0] == "audit" and os.environ.get("STAND_IN_AUDIT_NO_REPORT"):
    raise SystemExit(2)
elif args[0] == "audit":
    problem = os.environ.get("STAND_IN_AUDIT_PROBLEM")
    put(opt("--out"), json.dumps({"ok": not problem, "problems": [problem] if problem else [], "warnings": []}))
    if problem:
        print(f"audit: {pathlib.Path(args[1]).name}: 1 problem(s)", file=sys.stderr)
        raise SystemExit(1)
elif args[0] == "boxes":
    put(opt("--out"), json.dumps({"name": pathlib.Path(args[1]).stem, "boxes": []}))
elif args[0] == "sheet":
    put(opt("--out") / "index.json", "{}\n")
    put(opt("--out") / "review.html", "<html></html>\n")
'''


def _voiced_spec(build):
    """One take (00-home: CAMLOG, the 45 s take) whose first piece has three captions, two of them narrated and one
    of those with a box, then a wait; a narrated card; two reels (the build's own narrations taken out)."""
    spec = _unsaid(build)
    spec["clips"] = {"00-home": [
        build.piece("00-home", 3.5, 41.5, ko=[
            build.beat("shot:wide", "허브 화면 한 곳에서 허브를 봅니다", say="허브 화면의 홈입니다. 여기서 모두 봅니다."),
            build.beat("shot:flow1", "흐름 1은 허브가 심사하는 길입니다", say="흐름 일은 허브가 심사하는 길입니다",
                       box=[100, 200, 300, 120], what=["흐름 1의 설명"]),
            build.beat("asked", "개발자가 허브에 묻습니다")]),
        build.piece("00-home", 41.5, 44.0, speed=4)]}
    spec["cards"]["ko"]["card-intro"]["say"] = "팀은 스스로 올리고 플랫폼팀은 한 곳에서 관리합니다."
    spec["reels"] = {"main": ["card-intro", "00-home", "card-summary"], "stage-1": ["card-ch0", "00-home"]}
    return spec


VOICED_PIECES = ["00-home.1", "00-home.2", "00-home.3", "00-home.4"]


def _voiced_setup(tmp_path, monkeypatch, take):
    """The build module, the spec of _voiced_spec, an out folder with the raw take, its camlog and the card pictures
    the silent build left, the stand-in plugin, and a function that returns the plugin calls so far."""
    build = _build()
    out = tmp_path / "out"
    (out / "raw").mkdir(parents=True)
    shutil.copy(take, out / "raw" / "00-home.webm")
    (out / "raw" / "00-home.camlog.json").write_text(json.dumps(CAMLOG))
    (out / "cards" / "ko").mkdir(parents=True)
    for card in ("card-intro", "card-summary", "card-ch0"):
        for ext in (".png", ".mp4"):
            (out / "cards" / "ko" / f"{card}{ext}").write_text("silent card\n")
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    for f in ("edit_demo.py", "make_cards.py", "check_demo.py"):
        (plugin / f).write_text(STAND_IN_PLUGIN)
    monkeypatch.setenv("DEMO_VIDEO_PLUGIN", str(plugin))
    monkeypatch.delenv("STAND_IN_AUDIT_PROBLEM", raising=False)
    monkeypatch.delenv("STAND_IN_AUDIT_NO_REPORT", raising=False)
    log = plugin / "calls.jsonl"

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return build, _voiced_spec(build), out, calls


def _files(out: Path) -> dict:
    return {f.relative_to(out).as_posix(): (f.stat().st_mtime_ns, f.read_bytes()) for f in out.rglob("*") if f.is_file()}


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_voice_outputs_never_overwrite_the_silent_ones(tmp_path, monkeypatch, take_45s):
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    build.run(spec, out=out, check_only=True)                      # the silent build's scripts and manifests
    for rel in ("clips/ko/00-home.1.mp4", "clips/ko/00-home.2.mp4", "reels/hosting-hub-main-ko.mp4",
                "reels/hosting-hub-stage-1-ko.mp4"):                # and its clips and reels
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text("silent\n")
    for f in out.rglob("*"):
        if f.is_file():
            os.utime(f, ns=(10**18, 10**18))                       # an old time, so that a rewrite shows too
    before = _files(out)
    build.run_voice(spec, "ko", out, check_only=False)
    after = _files(out)
    written = {p for p in after if before.get(p) != after[p]}
    assert set(before) <= set(after)
    assert sorted(p for p in written if not ("-voice" in p or p.startswith(("voice/", "reports/")))) == []
    assert written == {*(f"scripts/ko-voice/{n}.json" for n in VOICED_PIECES),
                       *(f"clips/ko-voice/{n}.mp4" for n in VOICED_PIECES),
                       "voice/ko/lines.json", "voice/ko/readings.json", "voice/ko/voice.json",
                       *(f"voice/ko/{n}.mp3" for n in ("card-intro", "00-home.1", "00-home.2")),
                       *(f"reels/hosting-hub-{r}-ko-voice{ext}" for r in ("main", "stage-1")
                         for ext in (".json", ".mp4", ".voice.json")),
                       *(f"reports/{r}-ko-voice/{f}" for r in ("main", "stage-1")
                         for f in ("texts.json", "audit.json", "boxes/00-home.2.json", "index.json", "review.html"))}
    # a card picture that is missing is made where the silent build makes it, from texts the voiced build writes
    # under voice/; the silent build's cards.json and its other cards stay as they are
    for f in ("card-intro.png", "card-intro.mp4"):
        (out / "cards" / "ko" / f).unlink()
    before = _files(out)
    build.run_voice(spec, "ko", out, check_only=False)
    after = _files(out)
    outside = sorted(p for p in after if before.get(p) != after[p]
                     and not ("-voice" in p or p.startswith(("voice/", "reports/"))))
    assert outside == ["cards/ko/card-intro.mp4", "cards/ko/card-intro.png"]
    made = json.loads((out / "voice" / "ko" / "cards.json").read_text(encoding="utf-8"))
    assert made == {"card-intro": {"seconds": 4, "lines": build.card_lines(spec["cards"]["ko"]["card-intro"])}}


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_voice_check_writes_scripts_lines_and_manifests_and_cuts_nothing(tmp_path, monkeypatch, capsys, take_45s):
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    monkeypatch.delenv("DEMO_VIDEO_PLUGIN")                        # a check needs no plugin
    monkeypatch.setattr(build, "SPEC", spec)
    build.main(["--voice", "--check", "--out", str(out)])
    assert calls() == []
    written = sorted(p for p in _files(out) if not p.startswith(("raw/", "cards/")))
    assert written == ["reels/hosting-hub-main-ko-voice.json", "reels/hosting-hub-stage-1-ko-voice.json",
                       "reports/main-ko-voice/texts.json", "reports/stage-1-ko-voice/texts.json",
                       *(f"scripts/ko-voice/{n}.json" for n in VOICED_PIECES), "voice/ko/lines.json",
                       "voice/ko/readings.json"]
    def read(rel):
        return json.loads((out / rel).read_text(encoding="utf-8"))
    first, second, third = spec["clips"]["00-home"][0]["beats"]["ko"]
    assert read("voice/ko/lines.json") == {"card-intro": spec["cards"]["ko"]["card-intro"]["say"],
                                           "00-home.1": first["say"], "00-home.2": second["say"]}
    assert read("voice/ko/readings.json") == build.READINGS["ko"]
    assert [(s["start"], s["end"], s["speed"]) for s in (read(f"scripts/ko-voice/{n}.json") for n in VOICED_PIECES)] == [
        (3.5, 14.71, 1.25), (14.71, 19.8, 1.25), (19.8, 41.5, 1.25), (41.5, 44.0, 4)]
    assert read("scripts/ko-voice/00-home.2.json")["beats"] == [
        {"at": "shot:flow1", "text": second["text"], "box": [100, 200, 300, 120], "hold": True}]
    assert read("scripts/ko-voice/00-home.3.json")["beats"] == [{"at": "asked", "text": third["text"]}]
    assert read("scripts/ko-voice/00-home.4.json")["beats"] == []
    assert read("reels/hosting-hub-stage-1-ko-voice.json") == {"fade": 0.4, "voice_gap": 0.6, "voice_tail": 1.0,
                                                               "loudness": -16.0, "segments": [
        {"image": "cards/ko/card-ch0.png", "seconds": 3},
        {"file": "clips/ko-voice/00-home.1.mp4", "group": "00-home", "fade_out": 0, "voice": "voice/ko/00-home.1.mp3",
         "voice_at": 0.62},                                         # (3.9 - 3.5) / 1.25 + 0.3
        {"file": "clips/ko-voice/00-home.2.mp4", "group": "00-home", "fade_in": 0, "fade_out": 0,
         "voice": "voice/ko/00-home.2.mp3", "voice_at": 0.46},     # (14.91 - 14.71) / 1.25 + 0.3
        {"file": "clips/ko-voice/00-home.3.mp4", "group": "00-home.3", "fade_in": 0, "fade_out": 0},   # no narration
        {"file": "clips/ko-voice/00-home.4.mp4", "group": "00-home", "fade_in": 0}]}
    main = read("reels/hosting-hub-main-ko-voice.json")["segments"]
    assert main[0] == {"image": "cards/ko/card-intro.png", "seconds": 4, "voice": "voice/ko/card-intro.mp3",
                       "voice_at": 0.3} and main[-1] == {"image": "cards/ko/card-summary.png", "seconds": 9}
    assert read("reports/main-ko-voice/texts.json") == {
        "card-intro": {"caption": spec["cards"]["ko"]["card-intro"]["title"],
                       "say": spec["cards"]["ko"]["card-intro"]["say"], "what": []},
        "00-home.1": {"caption": first["text"], "say": first["say"], "what": []},
        "00-home.2": {"caption": second["text"], "say": second["say"], "what": ["흐름 1의 설명"]}}
    assert set(read("reports/stage-1-ko-voice/texts.json")) == {"00-home.1", "00-home.2"}
    assert "3 narrations" in capsys.readouterr().out


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_each_reels_texts_are_keyed_by_the_names_of_its_narrated_segments(tmp_path, monkeypatch, take_45s):
    # the review page finds a voice's texts by the voice's name, which the plugin's reel takes from its segment's file
    # (the stem): a texts key that names no voice leaves a row without its texts, and the page is still written. The
    # split renames pieces (the second narration of 00-home.1 plays in 00-home.2), so the keys are the voiced names
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    build.run_voice(spec, "ko", out, check_only=True)
    for reel in spec["reels"]:
        texts = json.loads((out / "reports" / f"{reel}-ko-voice" / "texts.json").read_text(encoding="utf-8"))
        manifest = json.loads((out / "reels" / f"hosting-hub-{reel}-ko-voice.json").read_text(encoding="utf-8"))
        said = [s for s in manifest["segments"] if "voice" in s]
        names = [Path(s.get("file") or s["image"]).stem for s in said]
        assert sorted(texts) == sorted(names) and len(set(names)) == len(names), reel
        assert [Path(s["voice"]).stem for s in said] == names, reel


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_a_caption_without_room_in_its_own_piece_stops_the_voiced_build(tmp_path, monkeypatch, capsys, take_45s):
    # two captions 1 s apart fit one silent piece; split, the first has 0.64 s of its own piece, less than ROOM
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    spec["clips"]["00-home"][0]["beats"]["ko"][1:] = [build.beat("shot:wide", "흐름 1은 허브가 심사하는 길입니다", offset=1.0)]
    with pytest.raises(SystemExit) as stop:
        build.run_voice(spec, "ko", out, check_only=True)
    err = capsys.readouterr().err
    assert stop.value.code == 2 and "00-home.1: '허브 화면 한 곳에서 허브를 봅니다' falls at 3.90 s" in err
    assert not (out / "scripts").exists() and calls() == []


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_the_voiced_build_calls_clips_voice_reels_audit_boxes_and_sheet_in_that_order(tmp_path, monkeypatch, capsys,
                                                                                      take_45s):
    # the clips come before the voices: a box the clip step refuses stops the build before anything is synthesized
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    (out / "cards" / "ko" / "card-intro.png").unlink()            # a missing card picture is made after the clips
    build.run_voice(spec, "ko", out, check_only=False)
    done = calls()

    def step(call):                                                # the plugin's command: a script and its first word
        return call[0] if call[0] == "make_cards.py" else call[1]
    per_reel = ["reel", "audit", "boxes", "sheet"]                 # 00-home.2 is the reel's one piece with a box
    assert [step(c) for c in done] == ["clip", "clip", "clip", "clip", "make_cards.py", "voice", *per_reel, *per_reel]
    o = str(out)
    assert done[1][1:] == ["clip", f"{o}/raw/00-home.webm", "--script", f"{o}/scripts/ko-voice/00-home.2.json", "--out",
                           f"{o}/clips/ko-voice/00-home.2.mp4"]
    assert done[3][-1] == "--no-captions"                          # 00-home.4, the wait, has no caption
    assert done[4][1:] == [f"{o}/voice/ko/cards.json", "--out", f"{o}/cards/ko"]
    assert done[5][1:] == ["voice", f"{o}/voice/ko/lines.json", "--out", f"{o}/voice/ko", "--readings",
                           f"{o}/voice/ko/readings.json", "--hangul-only", "--voice", "Seoyeon", "--engine", "generative",
                           "--language", "ko-KR"]
    reel, report = f"{o}/reels/hosting-hub-main-ko-voice", f"{o}/reports/main-ko-voice"
    assert [c[1:] for c in done[6:10]] == [
        ["reel", f"{reel}.json", "--out", f"{reel}.mp4"],
        ["audit", f"{reel}.mp4", "--plan", f"{reel}.voice.json", "--tolerance=0.25", "--loudness=-16.0", "--out",
         f"{report}/audit.json"],
        ["boxes", f"{o}/scripts/ko-voice/00-home.2.json", "--raw", f"{o}/raw/00-home.webm", "--out",
         f"{report}/boxes/00-home.2.json"],
        ["sheet", f"{reel}.mp4", "--plan", f"{reel}.voice.json", "--texts", f"{report}/texts.json", "--boxes",
         f"{report}/boxes/00-home.2.json", "--out", report]]
    assert done[10][1:4] == ["reel", f"{o}/reels/hosting-hub-stage-1-ko-voice.json", "--out"]
    # the reel step runs in the out folder: its manifest names the clips, card pictures and voices relative to it
    cwd = [json.loads(line) for line in (Path(os.environ["DEMO_VIDEO_PLUGIN"]) / "cwd.jsonl").read_text().splitlines()]
    assert [where for call, where in zip(done, cwd, strict=True) if call[1] == "reel"] == [os.path.realpath(out)] * 2
    # a failed audit stops the build with the report's lines: nothing more is checked or built
    (Path(os.environ["DEMO_VIDEO_PLUGIN"]) / "calls.jsonl").unlink()
    problem = "voice 2 (00-home.1): sound expected at 4.92-9.00 s, no sound there"
    monkeypatch.setenv("STAND_IN_AUDIT_PROBLEM", problem)
    capsys.readouterr()
    with pytest.raises(SystemExit) as stop:
        build.run_voice(spec, "ko", out, check_only=False)
    assert stop.value.code == 2 and [step(c) for c in calls()] == ["clip", "clip", "clip", "clip", "voice", "reel",
                                                                   "audit"]
    err = capsys.readouterr().err
    assert problem in err and "hosting-hub-main-ko-voice.mp4" in err


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_an_audit_that_writes_no_report_never_shows_an_older_one(tmp_path, monkeypatch, capsys, take_45s):
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    old = out / "reports" / "main-ko-voice" / "audit.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"ok": False, "problems": ["an older run's problem"], "warnings": []}))
    monkeypatch.setenv("STAND_IN_AUDIT_NO_REPORT", "1")              # the audit exits 2 and writes nothing
    with pytest.raises(SystemExit) as stop:
        build.run_voice(spec, "ko", out, check_only=False)
    err = capsys.readouterr().err
    assert stop.value.code == 2 and "an older run's problem" not in err and not old.exists()
    assert "the audit exited 2 and wrote no readable report" in err


# build.run_voice on a spec given as a JSON file, in a process of its own: a test sees all the build prints, and a
# traceback would show
RUN_VOICE = r'''
import importlib.util, json, pathlib, sys
spec = importlib.util.spec_from_file_location("demo_video_build", sys.argv[1])
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
build.run_voice(json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")), "ko", pathlib.Path(sys.argv[3]))
'''
CLIPS_CARDS_VOICES = ["clip", "clip", "clip", "clip", "make_cards.py", "voice"]


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
@pytest.mark.parametrize("fail, says, ran", [
    ("clip:00-home.2", "edit_demo.py clip failed for the piece 00-home.2", ["clip", "clip"]),
    ("make_cards.py:", "make_cards.py failed for the card(s) card-intro", CLIPS_CARDS_VOICES[:-1]),
    ("voice:", "edit_demo.py voice failed for the narrations", CLIPS_CARDS_VOICES),
    ("reel:stage-1", "edit_demo.py reel failed for the reel stage-1",
     [*CLIPS_CARDS_VOICES, "reel", "audit", "boxes", "sheet", "reel"]),
    ("boxes:", "check_demo.py boxes failed for the piece 00-home.2 of the reel main",
     [*CLIPS_CARDS_VOICES, "reel", "audit", "boxes"]),
    ("sheet:", "check_demo.py sheet failed for the reel main",
     [*CLIPS_CARDS_VOICES, "reel", "audit", "boxes", "sheet"])], ids=["clip", "cards", "voice", "reel", "boxes", "sheet"])
def test_a_plugin_step_that_fails_stops_the_voiced_build_in_two_lines_without_a_traceback(tmp_path, monkeypatch,
                                                                                         take_45s, fail, says, ran):
    # the plugin's own line says what went wrong (a box the clip step refuses, a synthesis that failed); the build adds
    # one line naming the step and its piece, cards or reel, exits 2 and runs nothing after it
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    (out / "cards" / "ko" / "card-intro.png").unlink()            # so that the cards step runs too
    (tmp_path / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "run_voice.py").write_text(RUN_VOICE)
    r = subprocess.run([sys.executable, str(tmp_path / "run_voice.py"), str(BUILD), str(tmp_path / "spec.json"),
                        str(out)], capture_output=True, text=True, env=os.environ | {"STAND_IN_FAIL": fail}, timeout=120)
    step = fail.partition(":")[0]
    assert (r.returncode, r.stderr.splitlines()) == (2, [f"stand-in: {step} failed", f"build stopped: {says} (exit 1)"])
    assert [c[0] if c[0] == "make_cards.py" else c[1] for c in calls()] == ran


@pytest.mark.parametrize("opts, says", [
    ({"say": "허브 화면의 홈입니다.", "voice_at": "1.5"}, '"voice_at" must be a number of seconds'),
    ({"say": "허브 화면의 홈입니다.", "voice_at": True}, '"voice_at" must be a number of seconds'),
    ({"box": [100, 200, 300, 120], "what": ["표"], "box_delay": "1"}, '"box_delay" must be a number of seconds, 0 or more'),
    ({"box": [100, 200, 300, 120], "what": ["표"], "box_delay": -0.5}, '"box_delay" must be a number of seconds, 0 or more'),
    ({"box": [100, 200, 300, 120], "what": ["표"], "box_dur": 0}, '"box_dur" must be a number of seconds above 0'),
    ({"box": [100, 200, 300, 120], "what": ["표"], "box_dur": "2"}, '"box_dur" must be a number of seconds above 0'),
    ({"box_delay": 1.0}, '"box_delay" on a caption without a box'),
    ({"box_dur": 2.0}, '"box_dur" on a caption without a box'),
    ({"box": [100, 200, 300, 120], "what": ["표"], "box_delay": 0, "box_dur": 2.5}, None),
    ({"say": "허브 화면의 홈입니다.", "voice_at": 1}, None)])
def test_a_value_on_a_caption_that_cannot_be_used_stops_the_build(tmp_path, capsys, opts, says):
    build = _build()
    spec, beat = _first_caption_unboxed(build)
    beat.update(opts)
    found = build.narration_problems(spec, "ko")
    if says is None:
        assert found == []
        return
    assert len(found) == 1 and found[0].startswith(CAPTION) and says in found[0], found
    _voice_refused(build, spec, tmp_path)
    assert says in capsys.readouterr().err


@pytest.mark.parametrize("box, says", [
    ([21, 1095, 300, 117], "the box [21, 1095, 300, 117] has no size or lies outside the 1920x1080 frame"),  # y+h 1212
    ([-4, 200, 300, 120], "the box [-4, 200, 300, 120] has no size or lies outside the 1920x1080 frame"),
    ([1700, 200, 300, 120], "the box [1700, 200, 300, 120] has no size or lies outside the 1920x1080 frame"),
    ([100, 200, 0, 120], "the box [100, 200, 0, 120] has no size or lies outside the 1920x1080 frame"),
    ([[100, 200, 300, 120], [100, 1000, 300, 120]], "the box [100, 1000, 300, 120] has no size or lies outside"),
    ([100, 200, 300], "the box [100, 200, 300] needs four numbers [x, y, w, h]"),
    ([100, "200", 300, 120], "the box [100, '200', 300, 120] needs four numbers [x, y, w, h]"),
    ([0, 0, 1920, 1080], None),
    ([1599.6, 959.6, 320.4, 120.4], None),                       # each number rounded to a pixel first, as the plugin
    ("shot:wide", None)])                                         # a box from the camlog: the clip step checks it
def test_a_box_given_as_numbers_outside_the_frame_stops_the_voiced_build_before_anything_is_written(tmp_path, capsys,
                                                                                                   box, says):
    build = _build()
    spec, beat = _first_caption_unboxed(build)
    beat.update(box=box, what=["표"] * build.box_count(box))
    assert build.problems(spec, "ko") == []                       # the silent build draws no box
    found = build.narration_problems(spec, "ko")
    if says is None:
        assert found == []
        return
    assert len(found) == 1 and found[0].startswith(CAPTION) and says in found[0], found
    _voice_refused(build, spec, tmp_path)
    assert says in capsys.readouterr().err


@pytest.mark.parametrize("where, old, new", [
    (("21-review", 2), "ends_early", "ends_erly"),                # 21-review.3 would no longer end early
    (("21-review", 4), "box_dur", "box_durr"),                    # 21-review.5's box would show past the camera move
    ("card-summary", None, "box"),                                # a card has no box
    ("card-ch5", "say", "sya")])
def test_a_key_the_build_does_not_know_on_a_caption_or_a_card_stops_both_builds(tmp_path, capsys, where, old, new):
    # a misspelled key would otherwise be dropped without a word; the known keys are those the two builds read
    import copy
    build = _build()
    spec = copy.deepcopy(build.SPEC)
    if isinstance(where, tuple):
        take, i = where
        item = spec["clips"][take][i]["beats"]["ko"][0]
        who = f"{take}.{i + 1}: {item['text']!r}: "
    else:
        item, who = spec["cards"]["ko"][where], f"{where}: "
    item[new] = item.pop(old) if old else [100, 200, 300, 120]
    found = build.problems(spec, "ko")
    assert len(found) == 1 and found[0].startswith(who) and f"the key {new!r}" in found[0], found
    _refused(spec, tmp_path, new)                                 # the silent build
    assert found[0] in capsys.readouterr().err
    _voice_refused(build, spec, tmp_path)
    assert found[0] in capsys.readouterr().err


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
@pytest.mark.parametrize("voice_at, says", [
    (0.1, "lies before its caption's start at 0.16 s"),            # the caption starts 0.16 s into 00-home.2
    (4.2, "lies beyond its piece (4.07 s long)"),                   # 00-home.2 is (19.8 - 14.71) / 1.25 s long
    (0.16, None), (4.0, None)])
def test_a_voice_start_outside_its_piece_or_before_its_caption_stops_the_build(tmp_path, monkeypatch, capsys, take_45s,
                                                                              voice_at, says):
    # a voice never starts before its caption, and starts inside its piece; checked once the pieces are split
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    spec["clips"]["00-home"][0]["beats"]["ko"][1]["voice_at"] = voice_at
    if says is None:
        build.run_voice(spec, "ko", out, check_only=True)
        assert json.loads((out / "reels" / "hosting-hub-main-ko-voice.json").read_text())["segments"][2]["voice_at"] \
            == voice_at
        return
    with pytest.raises(SystemExit) as stop:
        build.run_voice(spec, "ko", out, check_only=True)
    err = capsys.readouterr().err
    assert stop.value.code == 2 and "00-home.2: '흐름 1은 허브가 심사하는 길입니다': \"voice_at\"" in err and says in err
    assert not (out / "scripts").exists() and calls() == []


@pytest.mark.parametrize("opts, says", [
    ({"ends_early": True}, '"ends_early" on a caption without "dur"'),
    ({"dur": 4.0, "ends_early": "yes"}, '"ends_early" must be true or false'),
    ({"dur": 4.0, "ends_early": True, "say": None}, '"ends_early" on a caption without a narration')])
def test_a_caption_that_cannot_end_early_without_dur_or_narration_stops_the_build(tmp_path, capsys, opts, says):
    import copy
    build = _build()
    spec = copy.deepcopy(build.SPEC)
    beat = spec["clips"]["00-home"][0]["beats"]["ko"][0]
    beat.update({k: v for k, v in opts.items() if v is not None})
    if opts.get("say", "") is None:
        beat.pop("say")
    found = build.narration_problems(spec, "ko")
    assert len(found) == 1 and found[0].startswith(CAPTION) and says in found[0], found
    _voice_refused(build, spec, tmp_path)
    assert says in capsys.readouterr().err


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
@pytest.mark.parametrize("opts, says", [
    # 00-home.1 of the test spec: its caption (shot:wide) starts 0.32 s into its piece 3.5..14.71
    ({"dur": 7.5}, "leaves 1.15 s of its piece after the caption, less than 2.0 s"),       # cut at 13.275
    ({"dur": 1.5}, "shows the caption 1.50 s, less than 2.0 s"),
    ({"dur": 4.0, "box": [100, 200, 300, 120], "what": ["표"], "box_dur": 3.0},
     'before its box ends at 4.64 s: shorten "box_dur" to 2.68 s or less'),                # the box waits 1.32 s
    ({"dur": 4.0, "box": [100, 200, 300, 120], "what": ["표"], "box_delay": 4.5}, "before its box would show (from 4.82 s)"),
    ({"dur": 4.0}, None),
    ({"dur": 4.0, "box": [100, 200, 300, 120], "what": ["표"], "box_dur": 2.5}, None),
    ({"dur": 4.0, "box": [100, 200, 300, 120], "what": ["표"]}, None)])
def test_a_caption_that_ends_early_keeps_room_on_both_sides_and_its_whole_box(tmp_path, monkeypatch, capsys, take_45s,
                                                                             opts, says):
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    spec["clips"]["00-home"][0]["beats"]["ko"][0].update(opts, ends_early=True)
    if says is None:
        build.run_voice(spec, "ko", out, check_only=True)
        scripts = sorted(f.name for f in (out / "scripts" / "ko-voice").iterdir())
        assert scripts == [f"00-home.{n}.json" for n in range(1, 6)]                        # the rest is 00-home.2
        rest = json.loads((out / "scripts" / "ko-voice" / "00-home.2.json").read_text())
        assert (rest["start"], rest["end"], rest["beats"]) == (8.9, 14.71, [])
        assert "00-home.1 -> 00-home.1, 00-home.2, 00-home.3, 00-home.4" in capsys.readouterr().out
        return
    with pytest.raises(SystemExit) as stop:
        build.run_voice(spec, "ko", out, check_only=True)
    err = capsys.readouterr().err
    assert stop.value.code == 2 and "00-home.1: '허브 화면 한 곳에서 허브를 봅니다': \"ends_early\"" in err and says in err
    assert not (out / "scripts").exists() and calls() == []


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_the_early_end_check_names_the_takes_in_the_order_of_the_spec(tmp_path, monkeypatch, capsys, take_45s):
    # six takes cut from one recording, each with a caption that ends too early: the lines come take by take as the
    # spec writes them (neither sorted nor in the order of a set, which may differ from run to run)
    build, spec, out, calls = _voiced_setup(tmp_path, monkeypatch, take_45s)
    takes = ["51-f", "11-b", "41-e", "01-a", "31-d", "21-c"]
    spec["clips"] = {t: [build.piece("00-home", 3.5, 14.0, ko=[
        build.beat("shot:wide", "허브 화면 한 곳에서 허브를 봅니다", dur=1.5, ends_early=True, say="허브 화면의 홈입니다.")])]
        for t in takes}
    spec["reels"] = {"main": ["card-intro", *takes]}
    with pytest.raises(SystemExit) as stop:
        build.run_voice(spec, "ko", out, check_only=True)
    lines = [line for line in capsys.readouterr().err.splitlines() if '"ends_early"' in line]
    assert stop.value.code == 2 and [line.split(":")[0] for line in lines] == [f"{t}.1" for t in takes], lines


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
// a note is merged the way the plugin's recorder writes it into the camlog: { t, kind, ...data }
const fakeRec = () => ({ notes: [], note(kind, data = {}) { this.notes.push({ t: this.now(), kind, ...data }); }, now: () => 1 });
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
# ways past a check of the command's text, in the layout Claude Code prints
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
            # further cases
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
    """The seven real dialogs kept from the takes, and every command and path of the lists above in that layout."""
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


def _permission_notes(g: dict) -> list[dict]:
    """The notes named `permission`, as a camlog holds them (without their time)."""
    return [{k: v for k, v in n.items() if k != "t"} for n in g["notes"] if n["kind"] == "permission"]


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
    # the storyboard never answers Yes: whatever the question (every kept real one, every command and path of the
    # lists above), it presses Escape, then sends the take's sentence; Enter goes out only after a look that finds no
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
        [note] = _permission_notes(g)
        assert note["answer"] == "no" and note["dialog"] in ("shell", "file", "unknown"), i


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
    assert _permission_notes(during) == [{"kind": "permission", "answer": "no", "dialog": "unknown"}]
    assert [k for k, _ in during["keys"]] == ["Enter", "Escape", "Escape", "Enter"]
    assert [k for k, _ in left_open["keys"]] == ["Escape", "Enter"]       # the open dialog first, then the request
    for name in ("during", "left_open"):
        assert got[name]["error"] == "", name
        _answered_with_escape_only(got[name], OWN_QUESTION, name)
    # an answer's numbered list is not a dialog: the request goes out with Enter, nothing is answered
    assert [k for k, _ in plain["keys"]] == ["Enter"] and plain["error"] == ""
    assert not _permission_notes(plain)


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
    assert _permission_notes(g) == [{"kind": "permission", "answer": "no", "dialog": "file"}]
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
    assert not _permission_notes(got)


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


# A review page, scripted: each look gives the strip's steps (strip() calls evaluate with a scope) and the two pills
# of that look (the record's and the run's; evaluate without an argument). The recorder's clock moves one second per
# hold, and it merges a note as the plugin's recorder does.
REVIEW_PAGE = """
const reviewPage = looks => {
  let i = -1;
  return { evaluate: async (fn, scope) => {
    if (scope !== undefined) { i = Math.min(i + 1, looks.length - 1); return looks[i].steps.map(([name, state]) => ({ name, state })); }
    const l = looks[Math.max(i, 0)];
    return { record: l.record, run: l.run };
  } };
};
const clockRec = () => { let t = 0; return { notes: [], now: () => t, tick: () => { t += 1; },
  note(kind, data = {}) { this.notes.push({ t, kind, ...data }); } }; };
const clockCam = rec => ({ shots: [], async hold() { rec.tick(); }, async focus(key) { this.shots.push([rec.now(), key]); } });
"""
STEPS = ["Read", "Scan", "Grant"]


def _look(states: str, run: str, record: str) -> dict:
    """One look of the page: the steps' states (one letter each: p passed, r running, w waiting, f failed)."""
    word = {"p": "passed", "r": "running", "w": "waiting", "f": "failed"}
    return {"steps": [[n, word[c]] for n, c in zip(STEPS, states)], "run": run, "record": record}


def _reviews(cases: dict, tmp_path) -> dict:
    """Run waitForReview once per case ({looks, until, prefix?, seen?}) against the scripted page: its result, the
    notes (time and name) and the 'steps' shots (time and key)."""
    given = tmp_path / "reviews.json"
    given.write_text(json.dumps(cases), encoding="utf-8")
    run = """import fs from 'node:fs';
import { waitForReview } from './hub.mjs';
""" + REVIEW_PAGE + f"""
const cases = JSON.parse(fs.readFileSync({json.dumps(str(given))}, 'utf8'));
""" + """const out = {};
for (const [name, c] of Object.entries(cases)) {
  const page = reviewPage(c.looks), rec = clockRec(), cam = clockCam(rec);
  const result = await waitForReview(page, rec, cam, { until: c.until, prefix: c.prefix, seen: c.seen });
  out[name] = { result, notes: rec.notes.map(n => [n.t, n.kind]), shots: cam.shots };
}
console.log(JSON.stringify(out));"""
    return json.loads(_node(run, tmp_path))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_wait_for_a_review_notes_each_change_and_ends_on_approved_failed_or_time(tmp_path):
    pending, approved = "PENDING_APPROVAL", "APPROVED"
    got = _reviews({
        "passes": {"until": 100, "looks": [_look("prw", "RUNNING", pending), _look("prw", "RUNNING", pending),
                                           _look("ppr", "RUNNING", pending), _look("ppp", "SUCCEEDED", approved)]},
        # the page first shows the earlier review, finished: its end is not this review's end
        "earlier_first": {"until": 100, "looks": [_look("ppp", "SUCCEEDED", pending), _look("prw", "RUNNING", pending),
                                                  _look("ppp", "SUCCEEDED", approved)]},
        # the record reads APPROVED one look before the run reads SUCCEEDED
        "record_first": {"until": 100, "looks": [_look("prw", "RUNNING", pending), _look("ppp", "RUNNING", approved),
                                                 _look("ppp", "SUCCEEDED", approved)]},
        "fails": {"until": 100, "looks": [_look("prw", "RUNNING", pending), _look("pfw", "FAILED", pending),
                                          _look("pfw", "FAILED", pending)]},
        "time": {"until": 3, "looks": [_look("prw", "RUNNING", pending)]},
        "prefix": {"until": 100, "prefix": "quality_agent_", "seen": {"quality_agent_Read": "passed"},
                   "looks": [_look("prw", "RUNNING", pending), _look("ppp", "SUCCEEDED", approved)]},
    }, tmp_path)
    names = {k: [n for _, n in v["notes"]] for k, v in got.items()}
    assert got["passes"]["result"] == {"approved": True, "ended": "SUCCEEDED"}
    assert names["passes"] == ["Read_passed", "Scan_running", "Grant_waiting", "Scan_passed", "Grant_running",
                               "Grant_passed", "review_SUCCEEDED", "approved"]
    assert got["passes"]["shots"] == [[1, "steps"], [3, "steps"]]            # re-framed after each change, not after none
    assert got["earlier_first"]["result"] == {"approved": True, "ended": "SUCCEEDED"}
    assert names["earlier_first"].count("review_SUCCEEDED") == 1
    assert names["earlier_first"].index("review_SUCCEEDED") > names["earlier_first"].index("Scan_running")
    assert got["record_first"]["result"] == {"approved": True, "ended": "SUCCEEDED"}
    assert [t for t, n in got["record_first"]["notes"] if n == "approved"] == [3]
    assert got["fails"]["result"] == {"approved": False, "ended": "FAILED"}
    assert names["fails"][-1] == "review_FAILED" and "approved" not in names["fails"]
    assert got["time"]["result"] == {"approved": False, "ended": ""} and max(t for t, _ in got["time"]["notes"]) <= 3
    assert names["prefix"] == ["quality_agent_Scan_running", "quality_agent_Grant_waiting", "quality_agent_Scan_passed",
                               "quality_agent_Grant_passed", "quality_agent_SUCCEEDED", "approved"]


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
    assert (r.returncode, r.stdout) == (
        0, "texts: no 12-digit number, no e-mail address and no access key ID in 1 screens\n")


def test_the_text_check_finds_a_long_term_or_temporary_key_id_and_prints_it_masked(tmp_path):
    check = SCENES / "lib" / "check_texts.sh"
    texts = tmp_path / "take.texts.txt"
    # made up, and put together here so that no file of this repo holds the shape of a key
    for prefix in ("AKIA", "ASIA"):
        key = prefix + "ABCDEFGHIJ012345"
        texts.write_text(f"== 1.0 shell\ndev@dev-pc:~/work$ cat x\naws_access_key_id = {key}\n")
        r = subprocess.run([str(check), str(texts)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 1 and key not in r.stdout and "aws_access_key_id = <access key ID>" in r.stdout, prefix


def test_the_text_check_prints_a_found_line_without_control_characters_and_cut_short(tmp_path):
    texts = tmp_path / "take.texts.txt"
    # a bell splits a 12-digit number: dropping the bell must not print the joined number unmasked
    texts.write_bytes(("== 1.0 shell\nids 123456\x07789012 to someone@example.com " + CHOSEN).encode())
    r = subprocess.run([str(SCENES / "lib" / "check_texts.sh"), str(texts)], capture_output=True, timeout=30)
    out = r.stdout.decode()
    assert r.returncode == 1 and not CONTROLS.search(out), repr(out)
    assert "123456789012" not in out and "ids <12 digits> to someone@example.com" in out
    assert "red" in out and "\ttab" in out and out.rstrip("\n").endswith(" [cut]")
    assert max(len(line) for line in out.splitlines()) <= 300 + len(" [cut]")


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
