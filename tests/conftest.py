"""Shared fixtures. Every agent folder has files of the same name (agent.py, graph.py, main.py, hub_tools.py),
so a test loads an agent's module through load_agent, which puts that folder first on sys.path and forgets the
modules of the agent loaded before. load_variant does the same for a variant (variants/<name>/ of an agent folder):
it imports the files that publish would submit."""
import importlib
import io
import pathlib
import sys
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_MODULES = ("agent", "graph", "main", "hub_tools")


def _import_from(folder: pathlib.Path, module: str):
    sys.path.insert(0, str(folder))
    for m in AGENT_MODULES:
        sys.modules.pop(m, None)
    return importlib.import_module(module)


@pytest.fixture
def load_agent():
    original = list(sys.path)

    def load(name: str, module: str = "agent"):
        return _import_from(ROOT / "dev_team" / name, module)

    yield load
    sys.path[:] = original
    for m in AGENT_MODULES:
        sys.modules.pop(m, None)


@pytest.fixture
def load_variant(load_agent, tmp_path):
    """Load a module of an agent's variant from a temporary folder that holds the zip publish_agent.bundle makes
    for it, unpacked: the agent's files with the variant's files laid over them."""
    from platform_team.agent_catalog.publish_agent import bundle

    def load(name: str, variant: str, module: str = "agent"):
        folder = tmp_path / name / variant
        with zipfile.ZipFile(io.BytesIO(bundle(ROOT / "dev_team" / name, variant))) as z:
            z.extractall(folder)
        return _import_from(folder, module)

    return load      # load_agent puts sys.path and the agent modules back when the test ends
