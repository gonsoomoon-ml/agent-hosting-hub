"""Naming rules for every resource the hub creates. One place, so names never drift."""
import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REGION = "us-west-2"
DEFAULT_PREFIX = "hub"
DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
# The prefix starts every name: the policy engine takes [A-Za-z][A-Za-z0-9_]*, a Runtime [a-zA-Z][a-zA-Z0-9_]*,
# a gateway no "_", a bucket no upper case. platform_team/terraform/variables.tf checks the same rule.
PREFIX_PATTERN = r"[a-z][a-z0-9]{1,9}"

# .env (README, ".env"): only these three names are read from it, as NAME=value lines. Make, publish.sh, reject.sh,
# rollout.sh, guardrail.sh and e2e_hosting.py follow the same rule; whoever reads .env sets ENV_LOADED, so the commands it runs do not again.
HUB_VARIABLES = ("AWS_REGION", "DEMO_PREFIX", "MODEL_ID")
ENV_LOADED = "HUB_ENV_LOADED"


def env_file_updates(env, path: Path) -> dict[str, str]:
    """What to set in the environment `env` from the .env file at `path`: the hub's three values it holds (they win
    over the shell's; the last non-empty line of a name counts; `NAME=` with no value is the same as no line), and ENV_LOADED. Nothing when ENV_LOADED is set already (make, or
    a caller that read .env). No other line of the file is read, so credentials in it are never exported."""
    if env.get(ENV_LOADED):
        return {}
    path, found = Path(path), {}
    if path.is_file():
        for line in path.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name in HUB_VARIABLES and value:      # an empty value is no value, as for make
                found[name] = value
    return {**found, ENV_LOADED: "1"}

# A Runtime's ID is its name, "-" and 10 letters or digits AgentCore adds (as in the runs: <name>-eHcqNQ7n5v).
RUNTIME_ID_TAIL = r"-[A-Za-z0-9]{10}"
PACKAGES = "packages/"     # in the inbox bucket: the code packages the deploy build makes, packages/<agent>/...


def _camel(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_"))


@dataclass(frozen=True)
class Settings:
    region: str = DEFAULT_REGION
    prefix: str = DEFAULT_PREFIX
    model_id: str = DEFAULT_MODEL_ID

    def __post_init__(self):
        if not isinstance(self.prefix, str) or not re.fullmatch(PREFIX_PATTERN, self.prefix):
            raise ValueError(f"prefix {self.prefix!r} must be 2 to 10 lower-case letters or digits, starting with a "
                             "letter: it starts the names of the policy engine, the Runtimes, the gateways and the "
                             "bucket")

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

    def runtime_name(self, agent: str) -> str:
        """The agent's AgentCore Runtime: <prefix>_<agent>. AgentCore takes [a-zA-Z][a-zA-Z0-9_]{0,47}; a prefix has
        at most 10 characters and an agent name 31 (application_form), so every name fits."""
        return f"{self.prefix}_{agent}"

    def package_key(self, agent: str, code_version: str) -> str:
        """The agent's code package in the inbox, one per submitted object version (the deploy build writes it)."""
        return f"{PACKAGES}{agent}/{code_version}.zip"

    def runtime_id_pattern(self, agent: str) -> str:
        """The ID of this agent's Runtime, as a pattern to full-match: <runtime_name>-<10 letters or digits>."""
        return re.escape(self.runtime_name(agent)) + RUNTIME_ID_TAIL

    def runtime_arn_pattern(self, agent: str, account: str) -> str:
        """The ARN of this agent's Runtime in this account and Region, as a pattern to full-match."""
        return re.escape(f"arn:aws:bedrock-agentcore:{self.region}:{account}:runtime/") + self.runtime_id_pattern(agent)

    def target_name(self, agent: str) -> str:
        return _camel(agent)

    def bucket(self, account: str) -> str:
        return f"{self.prefix}-{account}-{self.region}"

    def ssm(self, *parts: str) -> str:
        return "/".join([f"/{self.prefix}", *parts])
