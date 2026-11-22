import json
import pathlib

DEV = pathlib.Path(__file__).resolve().parents[1] / "dev_team"
TEMPLATE = DEV / "agent_template"
PRELOADED = DEV / "preloaded_agents"
TEAM_AGENTS = sorted(p for p in DEV.iterdir() if p.is_dir() and p.name not in ("agent_template", "preloaded_agents",
                                                                                "__pycache__"))
# the agents there from the start that have code (a harness has none: no main.py, no hub_tools.py)
PRELOADED_WITH_CODE = sorted(p for p in PRELOADED.iterdir() if (p / "agent.json").is_file()
                             and json.loads((p / "agent.json").read_text())["framework"] != "harness")
AGENTS = TEAM_AGENTS + PRELOADED_WITH_CODE


def test_every_agent_keeps_the_templates_main_and_hub_tools():
    assert TEAM_AGENTS and [p.name for p in PRELOADED_WITH_CODE] == ["docs_adk"], "an agent folder is missing"
    for agent in AGENTS:
        for name in ("main.py", "hub_tools.py"):
            assert (agent / name).read_bytes() == (TEMPLATE / name).read_bytes(), f"{agent.name}/{name} differs from the template"
