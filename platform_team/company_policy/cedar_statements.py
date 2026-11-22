"""Cedar statements for the policy engine. Each statement is a template file; this fills in values."""
from pathlib import Path

_TEMPLATES = Path(__file__).parent / "policy_templates"


def _render(template: str, **values: str) -> str:
    text = (_TEMPLATES / template).read_text().strip()
    for key, value in values.items():
        text = text.replace(f"<{key}>", value)
    return text


def principal(account: str, role_name: str) -> str:
    return f'AgentCore::IamEntity::"arn:aws:sts::{account}:assumed-role/{role_name}"'


def tool_action(tool_id: str) -> str:
    return f'AgentCore::Action::"{tool_id}"'


def entry_action(target: str) -> str:
    return f'AgentCore::Action::"{target}___POST:/invocations"'


def tool_permit(account: str, role_name: str, tool_id: str, gateway_arn: str) -> str:
    return _render("tool-permit.cedar", account=account, role_name=role_name,
                   tool_id=tool_id, gateway_arn=gateway_arn)


def entry_permit(target: str, gateway_arn: str, account: str | None = None,
                 role_name: str | None = None) -> str:
    if account and role_name:
        return _render("entry-permit-review.cedar", account=account, role_name=role_name,
                       target=target, gateway_arn=gateway_arn)
    return _render("entry-permit.cedar", target=target, gateway_arn=gateway_arn)


def guard_secret(target: str, gateway_arn: str) -> str:
    return _render("guard-secret.cedar", target=target, gateway_arn=gateway_arn)
