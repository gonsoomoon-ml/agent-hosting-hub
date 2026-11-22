"""Validation of an agent's application form."""
import re

REQUIRED = ("name", "team", "framework", "tools")
NAME_PATTERN = r"^[a-z][a-z0-9_]{2,30}$"
TOOL_PATTERN = r"^[A-Za-z][A-Za-z0-9]*___[a-z][a-z0-9_]*$"   # <Target>___<tool>


def validate(app: dict, catalog_tools: set[str]) -> list[str]:
    """Return the problems found. An empty list means the application passes."""
    problems = [f"missing: {k}" for k in REQUIRED if k not in app]
    if "name" in app and not re.fullmatch(NAME_PATTERN, str(app["name"])):
        problems.append(f"name must match {NAME_PATTERN}")
    if "tools" in app:
        tools = app["tools"]
        if not tools:
            problems.append("tools must not be empty")
        for t in tools or []:
            if not isinstance(t, str) or not re.fullmatch(TOOL_PATTERN, t):
                problems.append(f"tool must look like <Target>___<tool>: {t}")
            elif t not in catalog_tools:
                problems.append(f"tool not in the catalog: {t}")
    return problems
