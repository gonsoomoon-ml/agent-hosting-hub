"""check_cleanup.py - list what of the hub is still in the account (reads only). `make destroy` runs it last.

    AWS_REGION=us-west-2 uv run python e2e_checks/check_cleanup.py

One line per kind of resource, with the names of the hub's that are still there, then
`still present: nothing` or the kinds that still hold something (exit code 1).
A name is the hub's when it has the hub's prefix the way the hub writes it: <prefix>-..., <prefix>_... (the Runtimes
<prefix>_<agent>), /<prefix>/.... Two more shapes are the names an AgentCore CLI deploy gives: <prefix> followed by
an upper-case letter (its projects and Runtimes) and AgentCore-<prefix>... (its CloudFormation stacks). The hub
makes no such names now; they are still looked for, so what an earlier version of the hub left is listed too.
Nothing is changed.
Not seen: the workload identity the registry service makes for itself. It is named registry-<registry ID>, without
the hub's prefix, so hub_name cannot tell it from another registry's; it goes with the registry (in the recorded run
a listing by hand showed it gone).
Printed output masks the account ID.
"""
import os
import re
import sys
from pathlib import Path

from botocore.exceptions import ClientError

from platform_team.shared_code.aws_helpers import Clients, all_items, mask
from platform_team.shared_code.config import Settings, env_file_updates


def hub_name(s: Settings, name: str) -> bool:
    """Whether a name is written the way the hub writes its names."""
    p = re.escape(s.prefix)
    return bool(re.match(rf"({p}[-_]|{p}[A-Z]|AgentCore-{p}[A-Z]|/{p}/)", name or ""))


def _pages(client, op: str, key: str, **kwargs) -> list:
    return [x for page in client.get_paginator(op).paginate(**kwargs) for x in page.get(key, [])]


def kinds(s: Settings, c: Clients) -> dict:
    """kind -> a function that returns the names of that kind of resource in the account, filtered by `hub_name`."""
    logs = lambda prefix: [g["logGroupName"] for g in _pages(c.logs, "describe_log_groups", "logGroups",
                                                             logGroupNamePrefix=prefix)]
    return {
        "gateways": lambda: [g["name"] for g in all_items(c.ctl.list_gateways, maxResults=100)],
        "policy engines": lambda: [e["name"] for e in all_items(c.ctl.list_policy_engines, maxResults=100)],
        "Runtimes": lambda: [r["agentRuntimeName"] for r in all_items(c.ctl.list_agent_runtimes, maxResults=100)],
        "workload identities": lambda: [w["name"] for w in all_items(c.ctl.list_workload_identities, maxResults=20)],
        "registries": lambda: [r["name"] for r in all_items(c.reg.list_registries, maxResults=100)],
        "Lambda functions": lambda: [f["FunctionName"] for f in _pages(c.lam, "list_functions", "Functions")],
        "CodeBuild projects": lambda: _pages(c.codebuild, "list_projects", "projects"),
        "state machines": lambda: [m["name"] for m in _pages(c.sfn, "list_state_machines", "stateMachines")],
        "EventBridge rules": lambda: [r["Name"] for r in _pages(c.events, "list_rules", "Rules")],
        "IAM roles": lambda: [r["RoleName"] for r in _pages(c.iam, "list_roles", "Roles")],
        "IAM policies": lambda: [p["PolicyName"] for p in _pages(c.iam, "list_policies", "Policies", Scope="Local")],
        "S3 buckets": lambda: [b["Name"] for b in c.s3.list_buckets()["Buckets"]],
        "SNS topics": lambda: [t["TopicArn"].rsplit(":", 1)[-1] for t in _pages(c.sns, "list_topics", "Topics")],
        "SQS queues": lambda: [u.rsplit("/", 1)[-1] for u in _pages(c.sqs, "list_queues", "QueueUrls",
                                                                     QueueNamePrefix=s.prefix)],
        "SSM parameters": lambda: [p["Name"] for p in _pages(
            c.ssm, "describe_parameters", "Parameters",
            ParameterFilters=[{"Key": "Name", "Option": "BeginsWith", "Values": [f"/{s.prefix}/"]}])],
        "CloudFormation stacks": lambda: [x["StackName"] for x in _pages(
            c.cfn, "list_stacks", "StackSummaries") if x["StackStatus"] != "DELETE_COMPLETE"],
        "log groups": lambda: (logs("/aws/lambda/") + logs("/aws/codebuild/") + logs("/aws/vendedlogs/states/")
                               + logs("/aws/vendedlogs/bedrock-agentcore/") + logs("/aws/bedrock-agentcore/runtimes/")),
        "log resource policies": lambda: [p["policyName"] for p in c.logs.describe_resource_policies()["resourcePolicies"]],
        # the gateways' log deliveries (agent_monitoring); a delivery has an ID only, so it goes by its source's name
        "log delivery sources": lambda: [x["name"] for x in _pages(c.logs, "describe_delivery_sources", "deliverySources")],
        "log delivery destinations": lambda: [x["name"] for x in _pages(c.logs, "describe_delivery_destinations",
                                                                         "deliveryDestinations")],
        "log deliveries": lambda: [x.get("deliverySourceName", "") for x in _pages(c.logs, "describe_deliveries",
                                                                                   "deliveries")],
        "CloudWatch alarms": lambda: [a["AlarmName"] for a in _pages(c.cw, "describe_alarms", "MetricAlarms")],
        "Bedrock guardrails": lambda: [g["name"] for g in _pages(c.bedrock, "list_guardrails", "guardrails")],
        "ECR repositories": lambda: [r["repositoryName"] for r in _pages(c.session.client("ecr"), "describe_repositories",
                                                                          "repositories")],
    }


def leftovers(s: Settings, c: Clients) -> dict[str, list[str]]:
    """kind -> the hub's names still there. A kind that cannot be listed holds one line that says why."""
    out = {}
    for kind, names in kinds(s, c).items():
        try:
            out[kind] = sorted(n for n in names() if hub_name(s, n.rsplit("/", 1)[-1] if kind == "log groups" else n))
        except ClientError as e:
            out[kind] = [f"cannot list: {e.response['Error']['Code']}"]
    return out


REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    # .env by the same rule as make and the commands (README, ".env"): before the settings are read
    os.environ.update(env_file_updates(os.environ, REPO / ".env"))
    s = Settings.from_env()
    c = Clients.for_settings(s)
    account = c.account
    print(f"== check_cleanup (prefix {s.prefix}, region {s.region})", flush=True)
    left = leftovers(s, c)
    for kind, names in left.items():
        print(mask(f"{kind}: {', '.join(names) or 'none'}", account), flush=True)
    present = [k for k, names in left.items() if names]
    print(f"still present: {', '.join(present) or 'nothing'}")
    return 1 if present else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # a traceback could print the account ID
        print(f"ERROR {type(e).__name__}: {re.sub(r'[0-9]{12}', '<ACCOUNT>', str(e))}")
        sys.exit(1)
