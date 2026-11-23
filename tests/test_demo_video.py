"""The demo video's developer PC (demo_video/tools/dev_pc): a container with Claude Code on Amazon Bedrock and the
developer role's temporary credentials. What can be checked without Docker or AWS: the outputs are git-ignored, the
settings hold no credential and allow only the listed tools, the MCP template has the documented shape, the Bedrock
session policy allows only the two invoke actions on the video's two models, and run.sh keeps its rules."""
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "demo_video"
DEV_PC = VIDEO / "tools" / "dev_pc"
SERVER = "hub-catalog"
MODELS = ("us.anthropic.claude-sonnet-5-5", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
ALLOWED = [f"mcp__{SERVER}__*", "Read(./**)", "Edit(./**)", "Bash(search:*)", "Bash(logs:*)", "Bash(publish:*)",
           "Bash(ls:*)", "Bash(cat:*)", "Bash(uv run pytest:*)"]


def _settings() -> dict:
    return json.loads((DEV_PC / "settings.json").read_text(encoding="utf-8"))


def test_the_video_outputs_and_the_credential_files_are_git_ignored():
    assert "out/" in (VIDEO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for path in ("demo_video/out/dev-pc/creds/developer.ini", "demo_video/out/dev-pc/creds/bedrock.json",
                 "demo_video/out/dev-pc/home/work/.mcp.json", "demo_video/out/raw/take.webm"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0, path


def test_the_settings_hold_no_credential_and_allow_only_the_listed_tools():
    s = _settings()
    assert set(s) == {"env", "awsCredentialExport", "permissions", "enabledMcpjsonServers"}
    assert s["permissions"]["allow"] == ALLOWED
    # Claude Code 2.1.330 starts in auto mode unless told otherwise (it said so at its first start in the container on
    # 2026-11-23): the mode that asks before any tool the list does not allow is set here, and no other mode
    assert set(s["permissions"]) == {"defaultMode", "allow", "deny"} and s["permissions"]["defaultMode"] == "default"
    assert s["permissions"].get("deny", []) == ["Read(//run/dev-pc/**)"]       # the credential files, never the tools'
    assert s["enabledMcpjsonServers"] == [SERVER]
    env = s["env"]
    assert env == {"CLAUDE_CODE_USE_BEDROCK": "1", "ANTHROPIC_MODEL": MODELS[0], "ANTHROPIC_DEFAULT_HAIKU_MODEL": MODELS[1],
                   "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1"}
    # Claude Code's own Bedrock token comes from a command that reads the file run.sh creds writes; the settings name
    # the file, never a value, and give the tools no AWS profile or key of their own
    assert s["awsCredentialExport"] == "cat /run/dev-pc/bedrock.json"
    text = (DEV_PC / "settings.json").read_text(encoding="utf-8")
    for word in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_BEARER_TOKEN",
                 "SecretAccessKey", "bypassPermissions", "dangerously", "Bash(*)", "Bash(aws"):
        assert word not in text, word
    assert not re.search(r"(AKIA|ASIA)[0-9A-Z]{16}", text)


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


def test_run_sh_keeps_its_rules():
    run = DEV_PC / "run.sh"
    assert os.access(run, os.X_OK)
    text = run.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "set -x" not in code and "xtrace" not in code and "set -euo pipefail" in code
    for sub in ("build", "creds", "up", "check", "term", "agent", "stop", "forget", "down"):
        assert re.search(r"^\s*%s\)" % sub, code, re.M), sub
    assert "umask 077" in code and "chmod 700" in code
    assert "--role-session-name developer" in code and "--name hub-video-claude" in code
    assert "--duration-seconds 14400" in code                                        # the Bedrock token: 4 hours
    assert re.search(r"ttyd -i lo -p 7681", code) and "-O" in code                   # loopback only, same origin
    assert not re.search(r"\s(-p|--publish)\s", code.split("docker run", 1)[1].split("\n\n", 1)[0])
    assert ".aws" not in code and "--privileged" not in code and "docker.sock" not in code
    assert "AWS_EC2_METADATA_DISABLED=true" in code               # no fallback to this PC's instance credentials,
    assert "ip route add blackhole 169.254.169.254/32" in code    # and no process reaches them at all
    assert "git -C" in code and "check-ignore" in code            # the checkout is the tracked files; creds are ignored


def test_run_sh_refuses_bad_usage_before_anything_runs():
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")} | {"PATH": "/usr/bin:/bin"}
    for args in ([], ["nope"], ["agent"], ["agent", "../x"]):
        r = subprocess.run([str(DEV_PC / "run.sh"), *args], capture_output=True, text=True, env=env, timeout=30)
        assert r.returncode == 2, (args, r.stdout, r.stderr)
        assert "usage: demo_video/tools/dev_pc/run.sh" in r.stdout + r.stderr or "agent" in r.stdout + r.stderr


def test_the_image_pins_its_tools_and_takes_nothing_from_this_pc():
    text = (DEV_PC / "Dockerfile").read_text(encoding="utf-8")
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", text, re.M))
    docker = re.sub(r"\$\{(\w+)\}", lambda m: args.get(m.group(1), m.group(0)), text)     # the ARGs as built
    assert args["CLAUDE_CODE_VERSION"] == "2.1.330"                                    # the version of this PC
    assert 'npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"' in text
    assert re.search(r'"mcp-proxy-for-aws==\d+\.\d+\.\d+"', docker) and "uv tool install" in docker
    assert re.search(r"^FROM node:22\.\d+\.\d+-bookworm-slim$", docker, re.M)
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
