"""The four commands a person types in the demo scenes (demo_scenes/ask, publish, search, logs): each is an executable
file that names the module it calls; publish refuses an agent or a variant that does not exist, before any call."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "demo_scenes"
MODULES = {"ask": "platform_team.agent_gateway.ask_agent", "publish": "platform_team.agent_catalog.publish_agent",
           "search": "platform_team.agent_catalog.search_catalog", "logs": "platform_team.agent_monitoring.agent_logs"}


def test_the_scene_commands_are_executable_and_call_their_modules():
    for name, module in MODULES.items():
        f = SCENES / name
        text = f.read_text(encoding="utf-8")
        assert os.access(f, os.X_OK), f"{name} is not executable"
        assert text.startswith("#!/usr/bin/env bash")
        assert module in text, f"{name} does not name {module}"
        assert "hub_env.sh" in text and "uv run --quiet" in text
    assert sorted(p.name for p in SCENES.iterdir() if p.is_file()) == ["README.md", "ask", "logs", "publish", "search"]


def test_the_scene_inputs_are_the_change_and_the_same_change_with_a_hidden_instruction():
    from e2e_checks.e2e_operations import HIDDEN
    ok = (SCENES / "inputs" / "change-ok.txt").read_text(encoding="utf-8")
    hidden = (SCENES / "inputs" / "change-with-hidden-instruction.txt").read_text(encoding="utf-8")
    assert HIDDEN not in ok and HIDDEN in hidden
    assert hidden.replace(HIDDEN, "").strip() != "" and all(line in hidden for line in ok.splitlines() if line.strip())
    assert len(ok.splitlines()) <= 12


def _run(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    return subprocess.run([str(SCENES / "publish"), *args], capture_output=True, text=True, env=env, timeout=60)


@pytest.mark.parametrize("args, says", [(["no_such_agent"], "quality_agent"), (["quality_agent", "v9-none"], "v2-loop"),
                                        (["../platform_team"], "quality_agent"), ([], "usage")])
def test_publish_refuses_an_agent_or_a_variant_that_does_not_exist_and_lists_those_that_do(args, says):
    r = _run(*args)
    assert r.returncode == 2 and says in (r.stdout + r.stderr)
    assert "Traceback" not in r.stdout + r.stderr


def test_publish_lists_the_variants_of_the_agent():
    r = _run("quality_agent", "v9-none")
    assert "v1-vulnerable" in r.stderr + r.stdout and "v2-loop" in r.stderr + r.stdout


def test_each_wrapper_run_from_another_folder_stops_at_bad_usage_before_any_call_and_prints_at_most_100_columns(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")} | {"AWS_EC2_METADATA_DISABLED": "true"}
    for name in MODULES:                                # no arguments: usage, exit 2, nothing was asked of AWS
        r = subprocess.run([str(SCENES / name)], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
        out = r.stdout + r.stderr
        assert r.returncode == 2 and "usage" in out and "Traceback" not in out, (name, out)
        assert all(len(line) <= 100 for line in out.splitlines()[:1]), name
    long = subprocess.run([str(SCENES / "ask"), "quality_agent"] + ["a very long prompt " * 20, "--timeout", "x"],
                          capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert long.returncode == 2 and len(long.stdout.splitlines()[0]) <= 100 and long.stdout.startswith("+ python -m ")


def test_publish_refuses_an_agent_without_variants_given_a_variant():
    r = _run("release_review", "v1-vulnerable")
    assert r.returncode == 2 and "no variants" in r.stdout + r.stderr
