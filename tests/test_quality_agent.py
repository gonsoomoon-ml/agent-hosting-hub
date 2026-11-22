import json
import pathlib

import pytest

from platform_team.agent_catalog.application_form import validate
from platform_team.agent_catalog.publish_agent import _catalog_tools, bundle
from platform_team.hosting_review import submission_check

A = pathlib.Path("dev_team/quality_agent")
VARIANT = "v1-vulnerable"


def test_application_names_only_catalog_tools():
    from platform_team.sample_tools.tool_schema import TARGETS
    catalog = {f"{t}___{x['name']}" for t, tools in TARGETS.items() for x in tools}
    assert validate(json.loads((A / "agent.json").read_text()), catalog) == []


def test_tools_go_through_the_hub_tool_gateway(load_agent, monkeypatch):
    agent = load_agent("quality_agent")
    seen = []
    monkeypatch.setattr(agent, "call_tool", lambda tool, args: seen.append((tool, args)) or "{}")
    agent.get_inspection_data("Q-1001"); agent.get_part_spec("P-100")
    assert seen == [("Quality___get_inspection_data", {"case_id": "Q-1001"}), ("Parts___get_part_spec", {"part_id": "P-100"})]


def test_the_vulnerable_variant_differs_only_by_the_marked_pin():
    base = (A / "requirements.txt").read_text().splitlines()
    bad = [l for l in (A / "variants/v1-vulnerable/requirements.txt").read_text().splitlines() if not l.startswith("#")]
    assert sorted(set(bad) - set(base)) == ["jinja2==2.11.2"]


def test_the_variant_has_every_base_line_and_the_marker_first():
    base = (A / "requirements.txt").read_text().splitlines()
    bad = (A / "variants/v1-vulnerable/requirements.txt").read_text().splitlines()
    assert bad[0] == "# demo only: a release with published advisories, to show the review failing"
    assert set(base) <= set(bad)


@pytest.mark.parametrize("variant", [None, VARIANT])
def test_both_bundles_pass_the_scan_line_rules(tmp_path, variant):
    """The variant is refused by the scan's audit, not by its layout or line rules."""
    (tmp_path / "agent.zip").write_bytes(bundle(A, variant))
    out = tmp_path / "unpacked"
    submission_check.unpack(tmp_path / "agent.zip", out)
    assert submission_check.check_layout(out) == []
    assert submission_check.check_requirements(out) == []
    assert sorted(p.name for p in out.iterdir()) == ["agent.py", "hub_tools.py", "main.py", "requirements.txt"]
    assert ("jinja2==2.11.2" in (out / "requirements.txt").read_text().splitlines()) == (variant is not None)


def test_application_passes_the_form_check():
    assert validate(json.loads((A / "agent.json").read_text()), _catalog_tools()) == []


def test_agent_imports_without_aws_or_environment(load_agent, monkeypatch):
    for name in ("HUB_REGION", "TOOL_GATEWAY_URL", "MODEL_ID", "AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)
    agent = load_agent("quality_agent")
    assert callable(agent.run) and agent._model is None


def test_a_refused_tool_answer_comes_back_unchanged(load_agent, monkeypatch):
    agent = load_agent("quality_agent")
    monkeypatch.setattr(agent, "call_tool", lambda tool, args: "ERROR: tool not allowed")
    assert agent.get_inspection_data("Q-1001") == "ERROR: tool not allowed"
    assert agent.get_part_spec("P-100") == "ERROR: tool not allowed"


@pytest.mark.parametrize("prompt", ["", "  \n "])
def test_a_blank_prompt_is_an_error_and_no_model_is_made(load_agent, monkeypatch, prompt):
    agent = load_agent("quality_agent")
    monkeypatch.setattr(agent, "new_agent", lambda: pytest.fail("the model must not be called"))
    answer, used = agent.run(prompt)
    assert answer.startswith("ERROR:") and used == []


def scripted_model(script):
    """A Strands model that plays back one scripted turn per call: ("tool", name, input) or ("text", text)."""
    from strands.models import Model
    turns = iter(script)

    class Scripted(Model):
        def update_config(self, **kw): pass
        def get_config(self): return {}
        async def structured_output(self, *a, **kw): raise NotImplementedError
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
            turn = next(turns)
            yield {"messageStart": {"role": "assistant"}}
            if turn[0] == "tool":
                yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{id(turn)}", "name": turn[1]}}}}
                yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn[2])}}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "tool_use"}}
            else:
                yield {"contentBlockDelta": {"delta": {"text": turn[1]}}}
                yield {"contentBlockStop": {}}
                yield {"messageStop": {"stopReason": "end_turn"}}
            yield {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, "metrics": {"latencyMs": 1}}}
    return Scripted()


def test_run_returns_the_answer_and_the_tools_the_model_called_in_order(load_agent, monkeypatch):
    agent = load_agent("quality_agent")
    calls = []
    monkeypatch.setattr(agent, "call_tool", lambda tool, args: calls.append((tool, args)) or '{"result": "PASS"}')
    model = scripted_model([("tool", "get_inspection_data", {"case_id": "Q-1001"}),
                            ("tool", "get_part_spec", {"part_id": "P-100"}),
                            ("text", "Q-1001 passed; P-100 is M4 x 12 mm.")])
    monkeypatch.setattr(agent, "_get_model", lambda: model)
    answer, used = agent.run("Did Q-1001 pass, and what is the part?")
    assert answer == "Q-1001 passed; P-100 is M4 x 12 mm."
    assert used == ["Quality___get_inspection_data", "Parts___get_part_spec"]
    assert calls == [("Quality___get_inspection_data", {"case_id": "Q-1001"}), ("Parts___get_part_spec", {"part_id": "P-100"})]


def test_a_question_that_needs_no_tool_reports_none(load_agent, monkeypatch):
    agent = load_agent("quality_agent")
    monkeypatch.setattr(agent, "_get_model", lambda: scripted_model([("text", "Which case?")]))
    assert agent.run("Is it fine?") == ("Which case?", [])


def test_a_model_failure_is_an_error_answer(load_agent, monkeypatch):
    agent = load_agent("quality_agent")
    for name in ("MODEL_ID", "HUB_REGION"):
        monkeypatch.delenv(name, raising=False)
    answer, used = agent.run("Did Q-1001 pass?")
    assert answer.startswith("ERROR:") and "MODEL_ID" in answer and used == []


def test_each_run_starts_a_fresh_conversation(load_agent, monkeypatch):
    agent = load_agent("quality_agent")
    monkeypatch.setattr(agent, "call_tool", lambda tool, args: "{}")
    models = iter([scripted_model([("tool", "get_part_spec", {"part_id": "P-100"}), ("text", "a")]),
                   scripted_model([("text", "b")])])
    monkeypatch.setattr(agent, "_get_model", lambda: next(models))
    assert agent.run("one")[1] == ["Parts___get_part_spec"]
    assert agent.run("two") == ("b", [])


def test_a_model_error_reaches_the_caller_without_the_account(load_agent, monkeypatch):    # final review M-5
    agent = load_agent("quality_agent")

    def denied():
        raise RuntimeError("User: arn:aws:sts::111122223333:assumed-role/hub-agent-quality_agent-role/s is not "
                           "authorized to perform: bedrock:InvokeModel " + "x" * 1000)
    monkeypatch.setattr(agent, "new_agent", denied)
    answer, used = agent.run("Did Q-1001 pass?")
    assert answer.startswith("ERROR: RuntimeError: User: arn:aws:sts::<ACCOUNT>:assumed-role/") and used == []
    assert "111122223333" not in answer and len(answer) < 400
