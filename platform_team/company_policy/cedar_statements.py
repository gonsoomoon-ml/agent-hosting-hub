"""Cedar statements for the policy engine. Each statement is a template file; this fills in values.

Every value goes inside a Cedar string, so a value must not be empty and must not hold a quote, a backslash or a
line break (it could end the string and change the statement). A template whose <placeholder> is left unfilled
is refused too: a statement is either made as written or not at all."""
import re
from pathlib import Path

_TEMPLATES = Path(__file__).parent / "policy_templates"
_UNSAFE = re.compile(r'["\\\r\n]')
_PLACEHOLDER = re.compile(r"<[a-z_]+>")


def _render(template: str, **values: str) -> str:
    text = (_TEMPLATES / template).read_text().strip()
    for key, value in values.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"{template}: empty value for <{key}>")
        if _UNSAFE.search(value):
            raise ValueError(f"{template}: <{key}> may not hold a quote, a backslash or a line break: {value[:80]!r}")
        text = text.replace(f"<{key}>", value)
    left = _PLACEHOLDER.search(text)
    if left:
        raise ValueError(f"{template}: unfilled {left.group(0)}")
    return text


def tool_permit(account: str, role_name: str, tool_id: str, gateway_arn: str) -> str:
    """The agent role may call this tool (tool gateway)."""
    return _render("tool-permit.cedar", account=account, role_name=role_name,
                   tool_id=tool_id, gateway_arn=gateway_arn)


def entry_permit(target: str, gateway_arn: str) -> str:
    """Every caller may call the agent behind this target (agent gateway): the users' permit, made at approval."""
    return _render("entry-permit.cedar", target=target, gateway_arn=gateway_arn)


def review_permit(target: str, gateway_arn: str, account: str, role_name: str) -> str:
    """Only this role may call the agent behind this target (agent gateway): the review's test call, before approval."""
    return _render("entry-permit-review.cedar", account=account, role_name=role_name,
                   target=target, gateway_arn=gateway_arn)


def guard_secret(target: str, gateway_arn: str) -> str:
    """A prompt that holds a secret is refused (agent gateway)."""
    return _render("guard-secret.cedar", target=target, gateway_arn=gateway_arn)


def guard_prompt(target: str, gateway_arn: str) -> str:
    """A prompt that is a prompt injection (confidence above 0.4) is refused (agent gateway)."""
    return _render("guard-prompt.cedar", target=target, gateway_arn=gateway_arn)


def stop_agent(target: str, gateway_arn: str, account: str, role_name: str) -> str:
    """Every call to the agent behind this target is refused, except from this role: the review's test call
    (agent gateway)."""
    return _render("stop-agent.cedar", account=account, role_name=role_name, target=target, gateway_arn=gateway_arn)
