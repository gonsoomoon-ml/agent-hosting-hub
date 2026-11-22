import pathlib

DEV = pathlib.Path(__file__).resolve().parents[1] / "dev_team"
TEMPLATE = DEV / "agent_template"
AGENTS = sorted(p for p in DEV.iterdir() if p.is_dir() and p.name not in ("agent_template", "__pycache__"))


def test_every_agent_keeps_the_templates_main_and_hub_tools():
    assert AGENTS, "no agent folder found"
    for agent in AGENTS:
        for name in ("main.py", "hub_tools.py"):
            assert (agent / name).read_bytes() == (TEMPLATE / name).read_bytes(), f"{agent.name}/{name} differs from the template"
