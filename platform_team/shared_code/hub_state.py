"""What Terraform made, as the Python side reads it: the values under SSM /<prefix>/platform/
(written by platform_team/terraform/outputs.tf)."""
from dataclasses import dataclass, field, fields

from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings


@dataclass(frozen=True)
class Platform:
    account: str = ""
    agent_gw: dict = field(default_factory=dict)      # id, arn, url
    tool_gw: dict = field(default_factory=dict)       # id, arn, url
    engine_id: str = ""
    engine_arn: str = ""
    registry_id: str = ""
    topic_arn: str = ""
    tool_lambda_arn: str = ""
    dev_role_arn: str = ""
    bucket: str = ""            # the hosting review's inbox (hosting_review module)
    machine_arn: str = ""       # the hosting review's state machine (hosting_review module)
    interceptor_arn: str = ""   # the custom guardrail's interceptor Lambda (custom_guardrail module)


class NotDeployed(RuntimeError):
    """Nothing under /<prefix>/platform/: the hub is not deployed in this account and Region."""


_GATEWAYS = {"agent_gw": "agent_gateway", "tool_gw": "tool_gateway"}


def load(s: Settings, c: Clients | None = None) -> Platform:
    """Read the platform values from SSM. A key that is not there yet (a module not deployed) reads as "".
    No value at all raises NotDeployed."""
    c = c or Clients.for_settings(s)
    path = s.ssm("platform")
    values = {p["Name"].removeprefix(path + "/"): p["Value"]
              for page in c.ssm.get_paginator("get_parameters_by_path").paginate(Path=path)
              for p in page["Parameters"]}
    if not values:
        raise NotDeployed(f"nothing under {path}/: run `make deploy` first")
    gateways = {f: {k: values.get(f"{key}_{k}", "") for k in ("id", "arn", "url")} for f, key in _GATEWAYS.items()}
    plain = {f.name: values.get(f.name, "") for f in fields(Platform) if f.name not in ("account", *_GATEWAYS)}
    return Platform(account=c.account, **gateways, **plain)
