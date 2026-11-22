"""Naming rules for every resource the hub creates. One place, so names never drift."""
import os
import re
from dataclasses import dataclass

DEFAULT_REGION = "us-west-2"
DEFAULT_PREFIX = "hub"
DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

MAX_PROJECT_NAME = 23  # AgentCore CLI limit
_PROJECT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _camel(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_"))


@dataclass(frozen=True)
class Settings:
    region: str = DEFAULT_REGION
    prefix: str = DEFAULT_PREFIX
    model_id: str = DEFAULT_MODEL_ID

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            region=os.environ.get("AWS_REGION") or DEFAULT_REGION,
            prefix=os.environ.get("DEMO_PREFIX") or DEFAULT_PREFIX,
            model_id=os.environ.get("MODEL_ID") or DEFAULT_MODEL_ID,
        )

    @property
    def agent_gateway(self) -> str:
        return f"{self.prefix}-agents"

    @property
    def tool_gateway(self) -> str:
        return f"{self.prefix}-tools"

    @property
    def engine(self) -> str:
        return f"{self.prefix}_pe"

    @property
    def registry(self) -> str:
        return f"{self.prefix}-registry"

    @property
    def topic(self) -> str:
        return f"{self.prefix}-alerts"

    @property
    def machine(self) -> str:
        return f"{self.prefix}-review"

    @property
    def rule(self) -> str:
        return f"{self.prefix}-on-submit"

    def role(self, key: str) -> str:
        return f"{self.prefix}-{key}-role"

    def agent_role(self, agent: str) -> str:
        return self.role(f"agent-{agent}")

    @property
    def agent_boundary(self) -> str:
        """The permissions boundary every agent role carries (hosting_review/terraform/iam.tf)."""
        return f"{self.prefix}-agent-boundary"

    def project_name(self, agent: str) -> str:
        name = self.prefix + _camel(agent)
        if len(name) > MAX_PROJECT_NAME or not _PROJECT_NAME.fullmatch(name):
            raise ValueError(
                f"project name {name!r} must start with a letter, be alphanumeric, "
                f"and be at most {MAX_PROJECT_NAME} characters"
            )
        return name

    def runtime_name(self, agent: str) -> str:
        return f"{self.project_name(agent)}_default_agent"

    def stack_name(self, agent: str) -> str:
        return f"AgentCore-{self.project_name(agent)}-default"

    def target_name(self, agent: str) -> str:
        return _camel(agent)

    def bucket(self, account: str) -> str:
        return f"{self.prefix}-{account}-{self.region}"

    def ssm(self, *parts: str) -> str:
        return "/".join([f"/{self.prefix}", *parts])
