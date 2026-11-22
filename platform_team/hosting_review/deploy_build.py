"""The deploy step of the hosting review. Runs in CodeBuild (buildspec_deploy.yml), after the Grant step made the
agent's execution role. Puts the team's code on AgentCore Runtime with the pinned AgentCore CLI and writes the
Runtime ARN to SSM, where the Entry step reads it.

    python -m platform_team.hosting_review.deploy_build

The team supplies code and requirements.txt only; the platform owns the deploy configuration:
  1 read the submission at the object version the catalog record names, unpack it and check its layout
  2 `agentcore create` makes a CDK project; its app/agent/ is replaced by the submission, and the platform
    writes agentcore/agentcore.json (runtime_skeleton/agentcore.json.tmpl) and app/agent/pyproject.toml
  3 `agentcore deploy`. The stack is AgentCore-<project>-default; when it exists, the Runtime gets a new version
  4 the Runtime ARN from the deploy output goes to SSM /<prefix>/agents/<agent>/runtime_arn

Environment: AGENT, CODE_KEY, CODE_VERSION, ROLE_ARN per run; BUCKET, PREFIX, TOOL_GW_URL, MODEL_ID on the
project; AWS_REGION from CodeBuild; AGENTCORE_CLI (the CLI's path) from the buildspec.
The pure parts (render_config, template_values, pyproject_from, runtime_arn) have unit tests; main() wires them to
the shell commands, S3 and SSM. Nothing calls AWS at import time.
"""
import json
import os
import re
import shutil
import string
import subprocess
import tempfile
from pathlib import Path

from botocore.exceptions import ClientError

from platform_team.hosting_review.submission_check import check_layout, unpack
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings

TEMPLATE = Path(__file__).with_name("runtime_skeleton") / "agentcore.json.tmpl"
CLI_TEMPLATE = "agent-python-minimal"     # the CDK app is what the build takes from it; the code is replaced
CODE_LOCATION = Path("app", "agent")      # the template's codeLocation
REQUIRED_ENV = ("AGENT", "CODE_KEY", "CODE_VERSION", "ROLE_ARN", "BUCKET", "PREFIX", "TOOL_GW_URL", "MODEL_ID",
                "AWS_REGION")
ARN_KEY = "RuntimeArnOutput"              # the stack output key is ...RuntimeArnOutput<CDK hash>


# ================================================================== pure parts

def _settings(env: dict) -> Settings:
    return Settings(region=env["AWS_REGION"], prefix=env["PREFIX"], model_id=env["MODEL_ID"])


def template_values(env: dict) -> dict[str, str]:
    """The values that fill agentcore.json.tmpl, from the build's environment."""
    agent = env["AGENT"]
    s = _settings(env)
    return {"PROJECT": s.project_name(agent), "ROLE_ARN": env["ROLE_ARN"], "HUB_REGION": s.region,
            "TOOL_GATEWAY_URL": env["TOOL_GW_URL"], "MODEL_ID": s.model_id, "AGENT_NAME": agent}


def render_config(template: str, values: dict[str, str]) -> str:
    """agentcore.json from the template. The template is JSON whose strings may hold ${NAME} placeholders;
    values fill those strings only, so a value can never change the structure."""
    def fill(node):
        if isinstance(node, str):
            try:
                return string.Template(node).substitute(values)
            except KeyError as e:
                raise ValueError(f"the template needs a value for {e.args[0]}") from None
        if isinstance(node, list):
            return [fill(n) for n in node]
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items()}
        return node
    return json.dumps(fill(json.loads(template)), indent=2) + "\n"


def pyproject_from(requirements: str, name: str) -> str:
    """A minimal pyproject.toml whose dependencies are the requirement lines of requirements.txt.
    The CLI's CodeZip packager installs the dependencies of the pyproject.toml it finds in the code location.
    pip options (-r, --index-url, --hash, ...) have no place there, so they are refused."""
    deps = []
    for raw in requirements.replace("\\\n", " ").splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        if re.search(r"(^|\s)--?[A-Za-z]", line):
            raise ValueError(f"requirements.txt: a pip option is not supported in the deploy build: {raw.strip()}")
        deps.append(" ".join(line.split()))
    lines = ["# Written by the deploy build from the submission's requirements.txt. The platform owns this file.",
             "[project]", f"name = {json.dumps(name)}", 'version = "0.1.0"', 'requires-python = ">=3.13"',
             "dependencies = [", *(f"    {json.dumps(d)}," for d in deps), "]"]
    return "\n".join(lines) + "\n"


def _json_documents(text: str) -> list:
    """Every JSON object in the text that starts at the beginning of a line (the CLI prints progress lines too)."""
    decoder, docs, end = json.JSONDecoder(), [], 0
    for m in re.finditer(r"^[ \t]*\{", text, re.M):
        if m.start() < end:
            continue
        try:
            doc, end = decoder.raw_decode(text, m.end() - 1)
        except ValueError:
            continue
        docs.append(doc)
    return docs


def _pairs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from _pairs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _pairs(v)


def runtime_arn(cli_output: str) -> str:
    """The Runtime ARN from the output of `agentcore deploy --json`."""
    found = sorted({v for doc in _json_documents(cli_output) for k, v in _pairs(doc)
                    if ARN_KEY in k and isinstance(v, str)})
    if not found:
        raise ValueError(f"no {ARN_KEY} in the agentcore deploy output (see the output above)")
    if len(found) > 1:
        raise ValueError(f"more than one Runtime ARN in the agentcore deploy output: {found}")
    return found[0]


# ================================================================== wiring (CodeBuild)

def say(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], cwd: Path) -> str:
    """Run a command, print its output as it comes, and return the output. A non-zero exit stops the build."""
    say(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    if proc.wait() != 0:
        what = f"{Path(cmd[0]).name} {cmd[1]}"
        raise SystemExit(f"deploy failed: `{what}` exited with {proc.returncode} (its output is above)")
    return "".join(lines)


def _aws(call, what: str):
    try:
        return call()
    except ClientError as e:
        err = e.response["Error"]
        raise SystemExit(f"deploy failed: {what}: {err['Code']}: {err['Message']}") from None


def main() -> None:
    env = dict(os.environ)
    missing = [k for k in REQUIRED_ENV if not env.get(k)]
    if missing:
        raise SystemExit(f"deploy refused: environment variables not set: {', '.join(missing)}")
    agent, s = env["AGENT"], _settings(env)
    project, cli = s.project_name(agent), env.get("AGENTCORE_CLI", "agentcore")
    c = Clients.for_settings(s)
    work = Path(tempfile.mkdtemp(prefix="hub-deploy-"))
    say(f"deploy {agent}: CLI project {project}, stack {s.stack_name(agent)}, Runtime {s.runtime_name(agent)}")

    # 1 the submission, at the version the catalog record names (the scan step checked the same version)
    where = f"s3://{env['BUCKET']}/{env['CODE_KEY']} version {env['CODE_VERSION']}"
    obj = _aws(lambda: c.s3.get_object(Bucket=env["BUCKET"], Key=env["CODE_KEY"], VersionId=env["CODE_VERSION"]),
               f"read the submission {where}")
    (work / "submission.zip").write_bytes(obj["Body"].read())
    src = work / "submission"
    try:
        unpack(work / "submission.zip", src)
    except ValueError as e:
        raise SystemExit(f"deploy refused: {e}") from None
    problems = check_layout(src)
    if problems:
        raise SystemExit(f"deploy refused: {'; '.join(problems)}")
    try:
        pyproject = pyproject_from((src / "requirements.txt").read_text(), project)
    except ValueError as e:
        raise SystemExit(f"deploy refused: {e}") from None
    say(f"submission unpacked: {where}")

    # 2 the CDK project from the pinned CLI; the submission is its code; the platform writes the configuration
    run([cli, "create", "--name", project, "--template", CLI_TEMPLATE, "--skip-install", "--skip-git", "--json"], work)
    root = work / project
    code = root / CODE_LOCATION
    shutil.rmtree(code, ignore_errors=True)
    shutil.copytree(src, code)
    for own in ("pyproject.toml", "uv.lock"):      # dependencies come from requirements.txt, the file the scan audited
        if (code / own).exists():
            say(f"the submission's {own} is replaced by the platform's")
            (code / own).unlink()
    (code / "pyproject.toml").write_text(pyproject)
    (root / "agentcore" / "agentcore.json").write_text(render_config(TEMPLATE.read_text(), template_values(env)))
    say(f"{CODE_LOCATION}/pyproject.toml and agentcore/agentcore.json written by the platform")

    # 3 deploy: a new stack the first time, a new Runtime version after that
    run(["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"], root / "agentcore" / "cdk")
    out = run([cli, "deploy", "--region", s.region, "--json", "--skip-bootstrap"], root)
    try:
        arn = runtime_arn(out)
    except ValueError as e:
        raise SystemExit(f"deploy failed: {e}") from None

    # 4 the Entry step reads the Runtime ARN here
    name = s.ssm("agents", agent, "runtime_arn")
    _aws(lambda: c.ssm.put_parameter(Name=name, Value=arn, Type="String", Overwrite=True), f"write {name}")
    say(f"runtime ARN written to {name}: {arn}")


if __name__ == "__main__":
    main()
