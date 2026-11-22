"""Shared fixtures. Every agent folder has files of the same name (agent.py, graph.py, main.py, hub_tools.py),
so a test loads an agent's module through load_agent, which puts that folder first on sys.path and forgets the
modules of the agent loaded before."""
import importlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_MODULES = ("agent", "graph", "main", "hub_tools")


@pytest.fixture
def load_agent():
    original = list(sys.path)

    def load(name: str, module: str = "agent"):
        sys.path.insert(0, str(ROOT / "dev_team" / name))
        for m in AGENT_MODULES:
            sys.modules.pop(m, None)
        return importlib.import_module(module)

    yield load
    sys.path[:] = original
    for m in AGENT_MODULES:
        sys.modules.pop(m, None)
