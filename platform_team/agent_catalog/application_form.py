"""Validation of an agent's application form. Publishing and the review's Read step both run it, so an application
whose names would not fit is refused before anything is made for it."""
import re

from platform_team.company_policy.policy_names import MAX_POLICY_NAME, policy_names

REQUIRED = ("name", "team", "framework", "tools")
TEXT_FIELDS, TEXT_LENGTH = ("team", "framework"), (1, 64)          # short strings: they name a folder and show on screen
# Lower-case segments joined by single underscores, each starting with a letter: the names made from it (the Runtime
# <prefix>_<agent>, the gateway target in CamelCase) are then one-to-one, and no agent name holds an upper-case letter.
# With a prefix of at most 10 characters, every Runtime name fits AgentCore's 48 (Settings.runtime_name).
NAME_PATTERN = r"^[a-z][a-z0-9]*(_[a-z][a-z0-9]*)*$"
NAME_LENGTH = (3, 31)
# <Target>___<tool>. A target starts with an upper-case letter and holds no underscore, so the tool permit name
# tool_<agent>_<Target>_<tool> splits one way only.
TOOL_PATTERN = r"^[A-Z][A-Za-z0-9]*___[a-z][a-z0-9_]*$"


def name_problems(name) -> list[str]:
    """What is wrong with an agent name on its own; an empty list means it is a valid name."""
    if not isinstance(name, str) or not re.fullmatch(NAME_PATTERN, name):
        return [f"name must match {NAME_PATTERN}"]
    low, high = NAME_LENGTH
    if not low <= len(name) <= high:
        return [f"name must have {low} to {high} characters: {name} has {len(name)}"]
    return []


def _length_problems(agent: str, tools: list[str]) -> list[str]:
    """The policy names made from the agent's name that would be too long, each with the room the agent name has."""
    problems = []
    for name in policy_names(agent, tools):
        if len(name) > MAX_POLICY_NAME:
            room = MAX_POLICY_NAME - (len(name) - len(agent))
            problems.append(f"policy name {name} has {len(name)} characters; a policy name may have at most "
                            f"{MAX_POLICY_NAME}, so for this policy the agent name may have at most {room} characters")
    return problems


def validate(app: dict, catalog_tools: set[str]) -> list[str]:
    """Return the problems found. An empty list means the application passes."""
    problems = [f"missing: {k}" for k in REQUIRED if k not in app]
    if "name" in app:
        problems += name_problems(app["name"])
    low, high = TEXT_LENGTH
    problems += [f"{k} must be a string of {low} to {high} characters" for k in TEXT_FIELDS
                 if k in app and not (isinstance(app[k], str) and low <= len(app[k]) <= high)]
    tools = app.get("tools")
    if "tools" in app:
        # the hub's tools the agent calls through the tool gateway; an empty list is an agent whose tools, if any, run
        # in its own process
        if not isinstance(tools, list):
            problems.append("tools must be a list of tool names")
            tools = []
        for t in tools or []:
            if not isinstance(t, str) or not re.fullmatch(TOOL_PATTERN, t):
                problems.append(f"tool must look like <Target>___<tool>: {t}")
            elif t not in catalog_tools:
                problems.append(f"tool not in the catalog: {t}")
    if "name" in app and not name_problems(app["name"]):
        good = [t for t in tools or [] if isinstance(t, str) and re.fullmatch(TOOL_PATTERN, t)]
        problems += _length_problems(app["name"], good)
    return problems
