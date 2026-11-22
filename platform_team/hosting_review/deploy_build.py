"""The deploy step of the hosting review. Runs in CodeBuild (buildspec_deploy.yml), after the Grant step made the
agent's execution role. Packages the team's code with its dependencies, creates or updates the agent's AgentCore
Runtime from that package (CreateAgentRuntime, UpdateAgentRuntime), and writes the Runtime ARN to SSM, where the
Entry step reads it.

    python -m platform_team.hosting_review.deploy_build

The team supplies code and requirements.txt only; the platform decides what is installed and how the Runtime runs:
  1 read the submission at the object version the catalog record names, unpack it, and check its layout and its
    requirements.txt with the scan's rules (submission_check). The submission's own build settings (PLATFORM_OWNED)
    are deleted, and the platform writes the requirement lines into its own requirements file (requirements_from)
  2 uv installs those requirements as wheels for the Runtime's platform (install_command); the package is what uv
    installed plus the submission's top-level .py files (package), uploaded to the inbox at Settings.package_key
  3 the Runtime <prefix>_<agent> (Settings.runtime_name) is created the first time and updated after that; the
    build waits until the version the call returns is READY (deploy)
  4 the Runtime ARN goes to SSM /<prefix>/agents/<agent>/runtime_arn

Environment: AGENT, CODE_KEY, CODE_VERSION, ROLE_ARN per run; BUCKET, PREFIX, TOOL_GW_URL, MODEL_ID on the
project; AWS_REGION from CodeBuild; UV_NO_CONFIG=1 from the buildspec, so uv reads no config file at all.
The pure parts (requirements_from, drop_build_settings, install_command, package, runtime_config) and deploy() have
unit tests; main() wires them to uv, S3, AgentCore and SSM. Nothing calls AWS at import time.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from botocore.exceptions import ClientError

from platform_team.hosting_review.submission_check import check_layout, check_requirements, parse_requirements, unpack
from platform_team.shared_code.aws_helpers import Clients, all_items, wait_status
from platform_team.shared_code.config import Settings

REQUIRED_ENV = ("AGENT", "CODE_KEY", "CODE_VERSION", "ROLE_ARN", "BUCKET", "PREFIX", "TOOL_GW_URL", "MODEL_ID",
                "AWS_REGION")
# Files of the submission that would change what uv installs or with which Python. The buildspec also sets
# UV_NO_CONFIG=1, so uv reads no config file at all.
PLATFORM_OWNED = ("pyproject.toml", "uv.lock", "uv.toml", ".python-version")
# What the Runtime runs (runtime_config): CPython 3.13 on Linux arm64, so the wheels are for that platform.
RUNTIME_PLATFORM, RUNTIME_PYTHON, RUNTIME_VERSION = "aarch64-manylinux2014", "3.13", "PYTHON_3_13"
ENTRY_POINT = "main.py"
CREATE_TRIES, CREATE_STEP = 8, 15      # the execution role Grant made a moment ago may not be usable yet
READY_WAIT, READY_STEP = 900, 10       # s, until the new Runtime version is READY
# An AccessDeniedException whose message holds one of these: the deploy role itself lacks the action (an AgentCore
# action, or passing the execution role). Trying again won't help.
OWN_ROLE_DENIED = ("is not authorized to perform: bedrock-agentcore:", "is not authorized to perform: iam:PassRole")


# ================================================================== pure parts

def _settings(env: dict) -> Settings:
    return Settings(region=env["AWS_REGION"], prefix=env["PREFIX"], model_id=env["MODEL_ID"])


def requirements_from(text: str) -> str:
    """The platform's requirements file: the requirement lines of the submission's requirements.txt, one per line,
    with comments, blank lines and continuations gone. The lines follow the scan's rule
    (submission_check.parse_requirements); a line it refuses raises ValueError. uv reads this file, not the team's."""
    deps, problems = parse_requirements(text)
    if problems:
        raise ValueError("; ".join(problems))
    return "".join(f"{d}\n" for d in deps)


def drop_build_settings(src: Path) -> list[str]:
    """Delete the submission's own build settings (PLATFORM_OWNED: what uv would read in that folder). They are
    deleted, not refused: the platform decides what is installed and from where. Returns the names deleted."""
    dropped = []
    for name in sorted(PLATFORM_OWNED):
        path = Path(src) / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
        else:
            continue
        dropped.append(name)
    return dropped


def install_command(requirements: Path, target: Path) -> list[str]:
    """uv installs the requirements into `target` as wheels only (no sdist, so no setup.py runs), for the Runtime's
    platform and Python, without compiling bytecode."""
    return ["uv", "pip", "install", "--quiet", "--no-compile", "--only-binary", ":all:",
            "--python-platform", RUNTIME_PLATFORM, "--python-version", RUNTIME_PYTHON,
            "--target", str(target), "-r", str(requirements)]


def package(src: Path, site: Path, out: Path) -> int:
    """Zip the Runtime's code: every file under `site` (what uv installed) and the submission's top-level .py files,
    names in sorted order, no __pycache__. A submitted .py file replaces an installed file of the same name.
    Returns the zip's size in bytes."""
    site, src, out = Path(site), Path(src), Path(out)
    files = {f.relative_to(site).as_posix(): f for f in site.rglob("*")
             if f.is_file() and "__pycache__" not in f.relative_to(site).parts}
    files.update({f.name: f for f in src.iterdir() if f.is_file() and f.suffix == ".py"})
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            z.write(files[name], name)
    return out.stat().st_size


def runtime_config(env: dict, key: str) -> dict:
    """The arguments that create and update the Runtime alike: the package at `key` in the inbox, the execution role
    Grant made, a public network, HTTP, and the hub's four environment variables."""
    s = _settings(env)
    return {
        "agentRuntimeArtifact": {"codeConfiguration": {"code": {"s3": {"bucket": env["BUCKET"], "prefix": key}},
                                                       "runtime": RUNTIME_VERSION, "entryPoint": [ENTRY_POINT]}},
        "roleArn": env["ROLE_ARN"],
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "environmentVariables": {"HUB_REGION": s.region, "TOOL_GATEWAY_URL": env["TOOL_GW_URL"],
                                 "MODEL_ID": s.model_id, "AGENT_NAME": env["AGENT"]},
        "description": "hosted agent",
    }


# ================================================================== the Runtime (takes the clients)

def say(msg: str) -> None:
    print(msg, flush=True)


def _create(c, name: str, config: dict) -> dict:
    """create_agent_runtime, tried again (CREATE_TRIES, CREATE_STEP apart) while the new execution role settles: the
    service answers ValidationException or AccessDeniedException until it can use the role. A denial of this step's
    own role (a message with one of OWN_ROLE_DENIED) and any other error raise at once."""
    for attempt in range(CREATE_TRIES):
        try:
            return c.ctl.create_agent_runtime(agentRuntimeName=name, **config)
        except ClientError as e:
            err = e.response["Error"]
            own = any(text in err.get("Message", "") for text in OWN_ROLE_DENIED)
            if attempt == CREATE_TRIES - 1 or own or err["Code"] not in ("ValidationException", "AccessDeniedException"):
                raise
            say(f"create_agent_runtime: {err['Code']}: {err.get('Message', '')[:160]} (try {attempt + 1} of "
                f"{CREATE_TRIES}, again in {CREATE_STEP}s)")
            time.sleep(CREATE_STEP)


def _version_status(c, rid: str, version: str) -> dict:
    """The Runtime's status as wait_status reads it. Until GetAgentRuntime shows `version`, the status names the
    version it shows, so an older version that is READY is not taken for the new one."""
    r = c.ctl.get_agent_runtime(agentRuntimeId=rid)
    shown = r.get("agentRuntimeVersion")
    status = r["status"] if shown == version else f"{r['status']} at version {shown}, waiting for {version}"
    return {**r, "status": status, "statusReason": r.get("failureReason")}


def deploy(c, env: dict, key: str, wait: int = READY_WAIT) -> dict:
    """Create the agent's Runtime from the package at `key`, or update it when one of its name exists (every page of
    ListAgentRuntimes is read). Wait until the version made is READY: a status ending in FAILED raises RuntimeError
    with the Runtime's failureReason, and no READY within `wait` seconds raises TimeoutError. Then write the Runtime
    ARN to SSM. Returns runtimeArn, runtimeId, version, created and readySeconds."""
    s, agent = _settings(env), env["AGENT"]
    name, config = s.runtime_name(agent), runtime_config(env, key)
    found = next((r for r in all_items(c.ctl.list_agent_runtimes, maxResults=100) if r["agentRuntimeName"] == name), None)
    if found:
        made = c.ctl.update_agent_runtime(agentRuntimeId=found["agentRuntimeId"], **config)
        say(f"Runtime {name} updated: {made['agentRuntimeId']} version {made['agentRuntimeVersion']}")
    else:
        made = _create(c, name, config)
        say(f"Runtime {name} created: {made['agentRuntimeId']} version {made['agentRuntimeVersion']}")
    rid, version, t0 = made["agentRuntimeId"], made["agentRuntimeVersion"], time.monotonic()
    ready = wait_status(lambda: _version_status(c, rid, version), ("READY",), f"Runtime {name}", timeout=wait,
                        step=READY_STEP)
    seconds = int(time.monotonic() - t0)
    param = s.ssm("agents", agent, "runtime_arn")
    c.ssm.put_parameter(Name=param, Value=ready["agentRuntimeArn"], Type="String", Overwrite=True)
    return {"runtimeArn": ready["agentRuntimeArn"], "runtimeId": rid, "version": version, "created": not found,
            "readySeconds": seconds}


# ================================================================== wiring (CodeBuild)

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


def main(env: dict | None = None, c=None) -> dict:
    """The deploy build: steps 1 to 4 above. `env` and `c` default to the process environment and real clients."""
    env = dict(os.environ if env is None else env)
    missing = [k for k in REQUIRED_ENV if not env.get(k)]
    if missing:
        raise SystemExit(f"deploy refused: environment variables not set: {', '.join(missing)}")
    agent, s = env["AGENT"], _settings(env)
    c = c or Clients.for_settings(s)
    work = Path(tempfile.mkdtemp(prefix="hub-deploy-"))
    say(f"deploy {agent}: Runtime {s.runtime_name(agent)}")

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
    problems = check_layout(src) + check_requirements(src)        # the scan's rules, checked again here
    if problems:
        raise SystemExit(f"deploy refused: {'; '.join(problems)}")
    for name in drop_build_settings(src):
        say(f"the submission's {name} is deleted: the platform decides what is installed")
    requirements = work / "requirements.txt"
    requirements.write_text(requirements_from((src / "requirements.txt").read_text()))
    say(f"submission unpacked: {where}")

    # 2 the dependencies as wheels for the Runtime, and the package with the submitted .py files
    site = work / "site"
    run(install_command(requirements, site), work)
    size = package(src, site, work / "package.zip")
    key = s.package_key(agent, env["CODE_VERSION"])
    with open(work / "package.zip", "rb") as body:
        _aws(lambda: c.s3.put_object(Bucket=env["BUCKET"], Key=key, Body=body), f"upload the package {key}")
    say(f"package uploaded: s3://{env['BUCKET']}/{key} ({size} bytes)")

    # 3, 4 the Runtime, its READY version, and its ARN in SSM for the Entry step
    try:
        out = deploy(c, env, key)
    except ClientError as e:
        err = e.response["Error"]
        raise SystemExit(f"deploy failed: Runtime {s.runtime_name(agent)}: {err['Code']}: {err['Message']}") from None
    except (RuntimeError, TimeoutError) as e:
        raise SystemExit(f"deploy failed: {e}") from None
    say(json.dumps(out))
    return out


if __name__ == "__main__":
    main()
