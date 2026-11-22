"""The names of the policies the hosting review makes for an agent, in one place. The form check refuses an
application whose names would not fit, the review's steps make the policies, and the cleanup removes them.

    entry_permit_<agent>             Approve: users may call the agent (agent gateway)
    review_permit_<agent>            Entry: only the review's test call may call it before approval
    tool_<agent>_<Target>_<tool>     Grant: the agent may call this tool (tool gateway)
    guard_secret_<agent>             Entry: a prompt that holds a secret is refused
    guard_prompt_<agent>             a prompt that attacks the agent is refused (agent gateway)
    stop_agent_<agent>               every call to the agent is refused, the review's test call excepted

One name has one kind, one agent and one tool: no kind's prefix is a prefix of another's; an agent name is
lower-case segments joined by single underscores (application_form); and a catalog target starts with an upper-case
letter and holds no underscore, so in a tool permit the agent ends where the first upper-case letter begins.
Nothing here imports the rest of the hub, so every part can import it.
"""
import re

MAX_POLICY_NAME = 48            # the policy engine's limit on a policy name (CreatePolicy name, max 48)

KINDS = {                       # kind -> the prefix of its names
    "entry_permit": "entry_permit_",
    "review_permit": "review_permit_",
    "tool": "tool_",
    "guard_secret": "guard_secret_",
    "guard_prompt": "guard_prompt_",
    "stop_agent": "stop_agent_",
}


def entry_permit_name(agent: str) -> str:
    return f"{KINDS['entry_permit']}{agent}"


def review_permit_name(agent: str) -> str:
    return f"{KINDS['review_permit']}{agent}"


def tool_policy_name(agent: str, tool_id: str) -> str:
    """tool_<agent>_<Target>_<tool> for the tool ID <Target>___<tool>."""
    target, tool = tool_id.split("___", 1)
    return f"{KINDS['tool']}{agent}_{target}_{tool}"


def tool_policy_pattern(agent: str) -> str:
    """Every tool permit name of this agent, whatever the tool (also one no longer in the catalog), as a pattern to
    full-match. It is exact for one agent: the agent name holds no upper-case letter and a target starts with one."""
    return re.escape(f"{KINDS['tool']}{agent}_") + r"[A-Z][A-Za-z0-9]*_[a-z][a-z0-9_]*"


def guard_secret_name(agent: str) -> str:
    return f"{KINDS['guard_secret']}{agent}"


def guard_prompt_name(agent: str) -> str:
    return f"{KINDS['guard_prompt']}{agent}"


def stop_agent_name(agent: str) -> str:
    return f"{KINDS['stop_agent']}{agent}"


def policy_names(agent: str, tools) -> list[str]:
    """Every policy name the review makes for an agent with these tool IDs, in the order the cleanup removes them:
    the entry permits first (a stopped agent must not open while the cleanup runs), then the tool permits, the guards,
    and the stop policy last."""
    return [entry_permit_name(agent), review_permit_name(agent),
            *(tool_policy_name(agent, t) for t in sorted(tools)), guard_secret_name(agent),
            guard_prompt_name(agent), stop_agent_name(agent)]
