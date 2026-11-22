#!/usr/bin/env python3
"""spike_cli_in_codebuild.py - does `agentcore deploy` (AgentCore CLI 1.0.3) run inside CodeBuild, under a deploy role?

The review pipeline's deploy step can put a team's agent on AgentCore Runtime in two ways:
  cli  CodeBuild runs `agentcore deploy` with an execution role made beforehand (this spike)
  api  CodeBuild packages the code and calls CreateAgentRuntime (passed in checks/whole-process)

  up    create the agent's execution role, the deploy role (the CodeBuild service role) and the CodeBuild project.
        The deploy role starts small: assume the CDK bootstrap roles, write its own build log. Actions that a build
        asked for (AccessDenied) are added to FOUND_BY_RUNNING, then `up test` runs again.
  test  start one build and wait. Then check the four pass criteria: the build SUCCEEDED; the stack holds the Runtime
        only and no IAM role was made; InvokeAgentRuntime returns 200; the build took 10 minutes or less.
        Also prints what later tasks need: the Runtime's name, and the environment variables set from agentcore.json.
  down  delete the stack, the CDK asset objects the builds uploaded, the project and its log group, the two roles.
        Then list what is left.

Usage:   AWS_REGION=us-west-2 uv run --with 'boto3>=1.44.9' --with requests python e2e_checks/spike_cli_in_codebuild.py up test
         ... spike_cli_in_codebuild.py down
Names:   everything this script creates starts with "hubspike". Printed output and saved logs mask the account ID.
The script keeps no state file: every step finds its resources by name.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, WaiterError

REGION = os.environ.get("AWS_REGION", "us-west-2")
P = "hubspike"
EXEC_ROLE, DEPLOY_ROLE, PROJECT = f"{P}-agent-role", f"{P}-deploy-role", f"{P}-deploy"
STACK = f"AgentCore-{P}-default"                 # the CLI names the stack AgentCore-<project>-<target>
LOG_GROUP = f"/aws/codebuild/{PROJECT}"
CLI_VERSION = "1.0.3"
TIME_BOX = 5                                     # builds
LIMIT_SECONDS = 600                              # pass criterion: the build takes 10 minutes or less
ENV_VARS = {"HUB_REGION": REGION, "AGENT_NAME": P}          # set through agentcore.json; the test reads them back
BUILD_LOG = Path(__file__).with_name("spike_cli_in_codebuild.last-build.log")

session = boto3.Session(region_name=REGION)
ACCOUNT = session.client("sts").get_caller_identity()["Account"]
BASE = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}"
CDK_BUCKET = f"cdk-hnb659fds-assets-{ACCOUNT}-{REGION}"
iam, cb, cfn, logs, s3 = (session.client(n) for n in ("iam", "codebuild", "cloudformation", "logs", "s3"))
ctl, data = session.client("bedrock-agentcore-control"), session.client("bedrock-agentcore")


def say(msg) -> None:
    print(mask(str(msg)), flush=True)


def mask(text: str) -> str:
    return text.replace(ACCOUNT, "<ACCOUNT>")


# ================================================================== roles

# The agent's execution role: the same trust and permissions as the review's grant step (checks/whole-process).
EXEC_TRUST = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
              "Action": "sts:AssumeRole", "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}}}]}
LG = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group"
WID = f"{BASE}:workload-identity-directory/default"
EXEC_PERMISSIONS = [
    {"Effect": "Allow", "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"], "Resource": [f"{LG}:/aws/bedrock-agentcore/runtimes/*"]},
    {"Effect": "Allow", "Action": ["logs:DescribeLogGroups"], "Resource": [f"{LG}:*"]},
    {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": [f"{LG}:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]},
    {"Effect": "Allow", "Action": ["bedrock-agentcore:InvokeGateway"], "Resource": [f"{BASE}:gateway/{P}-*"]},   # no gateway in this spike
    {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"},
    {"Effect": "Allow", "Action": ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                   "bedrock-agentcore:GetWorkloadAccessTokenForUserId"], "Resource": [WID, f"{WID}/workload-identity/*"]},
]

# The deploy role starts here: the CDK Toolkit assumes the bootstrap roles (deploy, file publishing, lookup), and the
# build writes its log. Everything else the CLI does with its own credentials is added below, one build at a time.
DEPLOY_START = [
    {"Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": ["arn:aws:iam::*:role/cdk-hnb659fds-*"]},
    {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
     "Resource": [f"{LG}:{LOG_GROUP}", f"{LG}:{LOG_GROUP}:*"]},
]
FOUND_BY_RUNNING: list[dict] = [        # actions a build asked for (AccessDenied), in the order they were found
    # build 1 (2026-11-22) passed without it. The CLI printed "skipping Transaction Search: ... not authorized to perform:
    # xray:GetTraceSegmentDestination" and went on. With it, the CLI only reads the account setting when it is on.
    {"Effect": "Allow", "Action": ["xray:GetTraceSegmentDestination"], "Resource": "*"},
]


def ensure_role(name: str, trust: dict, statements: list) -> str:
    try:
        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
        iam.update_assume_role_policy(RoleName=name, PolicyDocument=json.dumps(trust))
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust), Description="spike (safe to delete)")["Role"]["Arn"]
        say(f"role created: {name}")
    iam.put_role_policy(RoleName=name, PolicyName="spike", PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": statements}))
    return arn


def retry(fn, tries=8, wait=10, what=""):
    """Roles created seconds ago are not always usable yet."""
    for i in range(tries):
        try:
            return fn()
        except ClientError as e:
            if i == tries - 1:
                raise
            say(f"  {what}: {e.response['Error']['Message'][:110]} (retry in {wait}s)")
            time.sleep(wait)


# ================================================================== the build

# Node 22 and uv; the CLI; a new project from the Strands template; the execution role and the environment variables
# go into agentcore.json; the CDK app's packages; then the deploy. The template also declares an AgentCore Memory;
# the hub's agents do not use one, so it is removed (the agent's code skips memory when MEMORY_*_ID is not set).
BUILDSPEC = f'''\
version: 0.2
env:
  shell: bash
  variables:
    CLI: /tmp/cli/node_modules/.bin/agentcore
phases:
  install:
    runtime-versions:
      nodejs: 22
      python: 3.13
    commands:
      - python3 -m pip install --quiet uv
      - ln -sf "$(python3 -c 'import uv; print(uv.find_uv_bin())')" /usr/local/bin/uv
      - npm install --no-audit --no-fund --loglevel=error --prefix /tmp/cli @aws/agentcore@{CLI_VERSION}
      - echo "node $(node --version), $(uv --version), agentcore $($CLI --version)"
  build:
    commands:
      - cd /tmp && $CLI create --name {P} --template agent-python-strands --skip-install --skip-git --json
      - |
        cd /tmp/{P} && python3 - <<'PY'
        import json, os
        path = "agentcore/agentcore.json"
        config = json.load(open(path))
        runtime = config["runtimes"][0]
        runtime["executionRoleArn"] = os.environ["EXEC_ROLE_ARN"]
        runtime["envVars"] = json.loads(os.environ["RUNTIME_ENV"])
        config["memories"] = []
        json.dump(config, open(path, "w"), indent=2)
        print("runtimes[0]:", json.dumps(runtime))
        PY
      - cd /tmp/{P}/agentcore/cdk && npm install --no-audit --no-fund --loglevel=error
      - cd /tmp/{P} && START=$(date +%s) && $CLI deploy --region "$AWS_REGION" --json --skip-bootstrap && echo "DEPLOY_SECONDS $(( $(date +%s) - START ))"
  post_build:
    commands:
      - |
        cd /tmp/{P}/agentcore/cdk/cdk.out 2>/dev/null && python3 - <<'PY' || true
        import glob, json
        for manifest in glob.glob("*.assets.json"):
            for asset in json.load(open(manifest)).get("files", {{}}).values():
                for d in asset["destinations"].values():
                    print("SPIKE_ASSET", d["objectKey"])
        PY
'''


def ensure_project(deploy_role: str, exec_role: str) -> None:
    args = dict(name=PROJECT, description="spike: agentcore deploy inside CodeBuild", serviceRole=deploy_role, timeoutInMinutes=25,
                source={"type": "NO_SOURCE", "buildspec": BUILDSPEC}, artifacts={"type": "NO_ARTIFACTS"},
                environment={"type": "ARM_CONTAINER", "image": "aws/codebuild/amazonlinux-aarch64-standard:3.0",
                             "computeType": "BUILD_GENERAL1_SMALL", "environmentVariables": [
                                 {"name": "EXEC_ROLE_ARN", "value": exec_role, "type": "PLAINTEXT"},
                                 {"name": "RUNTIME_ENV", "value": json.dumps([{"name": k, "value": v} for k, v in ENV_VARS.items()]),
                                  "type": "PLAINTEXT"}]},
                logsConfig={"cloudWatchLogs": {"status": "ENABLED", "groupName": LOG_GROUP}})
    if cb.batch_get_projects(names=[PROJECT])["projects"]:
        cb.update_project(**args)
        say(f"CodeBuild project updated: {PROJECT}")
    else:
        retry(lambda: cb.create_project(**args), what=f"CodeBuild project {PROJECT}")
        say(f"CodeBuild project created: {PROJECT}")


def up() -> None:
    say(f"== up ({REGION})")
    exec_role = ensure_role(EXEC_ROLE, EXEC_TRUST, EXEC_PERMISSIONS)
    deploy_role = ensure_role(DEPLOY_ROLE, {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {
        "Service": "codebuild.amazonaws.com"}, "Action": "sts:AssumeRole"}]}, DEPLOY_START + FOUND_BY_RUNNING)
    found = [a for s in FOUND_BY_RUNNING for a in s["Action"]]
    say(f"deploy role: start set + {len(found)} found action(s) {found}")
    ensure_project(deploy_role, exec_role)


# ================================================================== test

def build_log(build: dict) -> list[str]:
    group, stream = build["logs"].get("groupName"), build["logs"].get("streamName")
    if not stream:
        return []
    lines, token = [], None
    while True:
        args = {"logGroupName": group, "logStreamName": stream, "startFromHead": True, **({"nextToken": token} if token else {})}
        page = logs.get_log_events(**args)
        lines += [e["message"].rstrip("\n") for e in page["events"]]
        if not page["events"] or page["nextForwardToken"] == token:
            return lines
        token = page["nextForwardToken"]


def run_build() -> dict:
    done = cb.list_builds_for_project(projectName=PROJECT)["ids"]
    say(f"build {len(done) + 1} of the time box ({TIME_BOX})")
    bid = cb.start_build(projectName=PROJECT)["build"]["id"]
    t0, next_note = time.monotonic(), 60
    while True:
        b = cb.batch_get_builds(ids=[bid])["builds"][0]
        if b["buildComplete"]:
            break
        if time.monotonic() - t0 >= next_note:                      # one progress line a minute
            say(f"  {next_note}s: {b['currentPhase']}")
            next_note += 60
        time.sleep(15)
    for ph in b["phases"]:
        if "durationInSeconds" in ph:
            say(f"  phase {ph['phaseType']:<16} {ph.get('phaseStatus', ''):<10} {ph['durationInSeconds']:>4}s")
    time.sleep(10)                                   # the last log lines arrive a little after the build ends
    lines = build_log(b)
    BUILD_LOG.write_text(mask("\n".join(lines)) + "\n")
    say(f"build log saved (account masked): {BUILD_LOG.name}, {len(lines)} lines")
    for line in lines:
        if re.search(r"AccessDenied|not authorized|UnauthorizedOperation|is not allowed|Transaction Search|DEPLOY_SECONDS|runtimes\[0\]|"
                     r"agentcore \d|\"status\"|error", line, re.I):
            say(f"  | {line[:400]}")
    return b


def stack_resources() -> list[dict]:
    try:
        return cfn.describe_stack_resources(StackName=STACK)["StackResources"]
    except ClientError:
        return []


def invoke(arn: str) -> tuple[int, str]:
    r = data.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=f"{P}-{uuid.uuid4()}", contentType="application/json",
                                  accept="application/json, text/event-stream",
                                  payload=json.dumps({"prompt": "What is 2 + 3? Use the add_numbers tool."}).encode())
    body = r["response"].read().decode(errors="replace")
    text = "".join(re.findall(r'"text":\s*"((?:[^"\\]|\\.)*)"', body))
    return r.get("statusCode", r["ResponseMetadata"]["HTTPStatusCode"]), text or body[-300:]


def test() -> None:
    say(f"== test ({REGION})")
    b = run_build()
    seconds = int((b["endTime"] - b["startTime"]).total_seconds())
    results = {"build SUCCEEDED": (b["buildStatus"] == "SUCCEEDED", b["buildStatus"])}
    res = stack_resources()
    types = sorted({r["ResourceType"] for r in res})
    real = [t for t in types if t != "AWS::CDK::Metadata"]           # CDK's metadata entry is not an AWS resource
    cdk_roles = [r["RoleName"] for page in iam.get_paginator("list_roles").paginate() for r in page["Roles"]
                 if r["RoleName"].startswith(STACK) or r["RoleName"].startswith(f"AgentCore-{P}")]
    results["stack holds the Runtime only, no role made"] = (real == ["AWS::BedrockAgentCore::Runtime"] and not cdk_roles,
                                                             f"stack resources {types}; roles made by the stack {cdk_roles}")
    rt = next((r for r in res if r["ResourceType"] == "AWS::BedrockAgentCore::Runtime"), None)
    if rt:
        detail = ctl.get_agent_runtime(agentRuntimeId=rt["PhysicalResourceId"])
        say(f"runtime: name {detail['agentRuntimeName']}, id {detail['agentRuntimeId']}, status {detail['status']}")
        say(f"runtime role is the execution role made by up: {detail['roleArn'].endswith(':role/' + EXEC_ROLE)}")
        env = detail.get("environmentVariables", {})
        say(f"runtime environment variables: {env}")
        say(f"environment variables from agentcore.json runtimes[0].envVars arrived: {all(env.get(k) == v for k, v in ENV_VARS.items())}")
        try:
            code, text = invoke(detail["agentRuntimeArn"])
        except ClientError as e:
            code, text = e.response["ResponseMetadata"]["HTTPStatusCode"], e.response["Error"]["Message"]
        results["InvokeAgentRuntime returns 200"] = (code == 200, f"{code}: {text[:200]}")
    else:
        results["InvokeAgentRuntime returns 200"] = (False, "no Runtime in the stack")
    results[f"build took {LIMIT_SECONDS // 60} minutes or less"] = (seconds <= LIMIT_SECONDS, f"{seconds}s from start to end")
    for name, (ok, note) in results.items():
        say(f"[{'PASS' if ok else 'FAIL'}] {name}: {note}")
    passed = all(ok for ok, _ in results.values())
    say(f"== {sum(ok for ok, _ in results.values())} of {len(results)} passed; DEPLOY_VARIANT = {'cli' if passed else 'api'}"
        + ("" if passed else " (unless a run inside the time box passes)"))


# ================================================================== down

def asset_keys() -> set[str]:
    """The CDK asset objects (code zip, template) the builds uploaded, as the post_build phase printed them."""
    keys = set()
    try:
        for page in logs.get_paginator("filter_log_events").paginate(logGroupName=LOG_GROUP, filterPattern='"SPIKE_ASSET"'):
            keys |= {m.group(1) for e in page["events"] for m in [re.search(r"SPIKE_ASSET (\S+)", e["message"])] if m}
    except ClientError:
        pass
    return keys


def quiet(fn, what=""):
    try:
        return fn()
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("ResourceNotFoundException", "NoSuchEntity", "ValidationError"):
            say(f"  {what}: {e.response['Error']['Code']}: {e.response['Error']['Message'][:140]}")


def runtimes() -> list[dict]:
    return [r for page in ctl.get_paginator("list_agent_runtimes").paginate() for r in page["agentRuntimes"]
            if r["agentRuntimeName"].startswith(P)]


def down() -> None:
    say(f"== down ({REGION})")
    keys = asset_keys()
    try:
        cfn.describe_stacks(StackName=STACK)
        stack_exists = True
    except ClientError:
        stack_exists = False
    if stack_exists:
        cfn.delete_stack(StackName=STACK)
        try:
            cfn.get_waiter("stack_delete_complete").wait(StackName=STACK, WaiterConfig={"Delay": 10, "MaxAttempts": 90})
            say(f"stack deleted: {STACK}")
        except WaiterError as e:
            say(f"  stack: {e}")
    for _ in range(60):                              # the Runtime goes with the stack; wait until it is gone
        if not runtimes():
            break
        time.sleep(5)
    for g in logs.describe_log_groups(logGroupNamePrefix=f"/aws/bedrock-agentcore/runtimes/{P}").get("logGroups", []):
        logs.delete_log_group(logGroupName=g["logGroupName"])
        say(f"log group deleted: {g['logGroupName']}")
    removed = 0
    for key in sorted(keys):                         # the bucket keeps versions: delete every version of each key
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=CDK_BUCKET, Prefix=key):
            for o in page.get("Versions", []) + page.get("DeleteMarkers", []):
                if o["Key"] == key:
                    s3.delete_object(Bucket=CDK_BUCKET, Key=key, VersionId=o["VersionId"])
                    removed += 1
    say(f"CDK asset objects deleted: {len(keys)} key(s), {removed} version(s)")
    if cb.batch_get_projects(names=[PROJECT])["projects"]:
        cb.delete_project(name=PROJECT)
        say(f"CodeBuild project deleted: {PROJECT}")
    quiet(lambda: logs.delete_log_group(logGroupName=LOG_GROUP), "log group")
    for name in (EXEC_ROLE, DEPLOY_ROLE):
        try:
            for pn in iam.list_role_policies(RoleName=name)["PolicyNames"]:
                iam.delete_role_policy(RoleName=name, PolicyName=pn)
            iam.delete_role(RoleName=name)
            say(f"role deleted: {name}")
        except iam.exceptions.NoSuchEntityException:
            pass

    # what is left
    left = {
        "stacks": [s["StackName"] for page in cfn.get_paginator("list_stacks").paginate() for s in page["StackSummaries"]
                   if s["StackName"].startswith(f"AgentCore-{P}") and s["StackStatus"] != "DELETE_COMPLETE"],
        "runtimes": [r["agentRuntimeName"] for r in runtimes()],
        "workload identities": [w["name"] for page in ctl.get_paginator("list_workload_identities").paginate()
                                for w in page["workloadIdentities"] if w["name"].startswith(P)],
        "CodeBuild projects": [n for n in cb.list_projects()["projects"] if n.startswith(P)],
        "roles": [r["RoleName"] for page in iam.get_paginator("list_roles").paginate() for r in page["Roles"]
                  if r["RoleName"].startswith(P) or r["RoleName"].startswith(f"AgentCore-{P}")],
        "log groups": [g["logGroupName"] for prefix in (f"/aws/codebuild/{P}", f"/aws/bedrock-agentcore/runtimes/{P}")
                       for g in logs.describe_log_groups(logGroupNamePrefix=prefix).get("logGroups", [])],
        "CDK asset objects": [k for k in keys if s3.list_object_versions(Bucket=CDK_BUCKET, Prefix=k).get("Versions")],
    }
    for what, names in left.items():
        say(f"  left {what}: {names or 'none'}")
    say(f"== down finished; still present: {[w for w, n in left.items() if n] or 'nothing'}")


if __name__ == "__main__":
    cmds = sys.argv[1:]
    if not cmds or any(c not in ("up", "test", "down") for c in cmds):
        sys.exit(__doc__)
    for c in cmds:
        {"up": up, "test": test, "down": down}[c]()
