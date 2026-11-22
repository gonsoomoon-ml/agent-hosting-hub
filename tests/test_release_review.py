import json
import pathlib

from platform_team.agent_catalog import publish_agent
from platform_team.agent_catalog.application_form import validate
from platform_team.agent_catalog.publish_agent import bundle
from platform_team.hosting_review import submission_check

FOLDER = pathlib.Path("dev_team/release_review")


def run(load_agent, prompt, verdict, tool_answer='{"request_id": "RR-1"}'):
    calls = []
    g = load_agent("release_review", "graph").build(call_tool=lambda tool, args: calls.append((tool, args)) or tool_answer,
              ask_model=lambda system, user: verdict)
    return g.invoke({"prompt": prompt}), calls

def test_a_violation_files_one_review_request(load_agent):
    out, calls = run(load_agent, "Change C-7 skips the canary stage.", "VIOLATION: canary stage skipped")
    assert [c[0] for c in calls] == ["Release___file_review_request"] and "RR-1" in out["answer"]

def test_no_violation_calls_no_tool(load_agent):
    out, calls = run(load_agent, "Change C-8 follows every rule.", "OK")
    assert calls == [] and out["tools_used"] == []


def test_the_request_names_the_change_and_the_reason(load_agent):
    out, calls = run(load_agent, "Change C-7 skips the canary stage.", "VIOLATION: canary stage skipped")
    assert calls[0][1] == {"change_id": "C-7", "summary": "canary stage skipped"}
    assert out["tools_used"] == ["Release___file_review_request"]


def test_a_refused_tool_call_is_reported_as_a_failure_not_a_request_number(load_agent):
    out, _ = run(load_agent, "Change C-7 skips the canary stage.", "VIOLATION: x", "ERROR: tool not allowed")
    assert "could not be filed" in out["answer"] and "tool not allowed" in out["answer"]
    assert "Review request:" not in out["answer"]


def test_a_model_failure_is_an_error_not_a_silent_pass(load_agent):
    def broken(system, user):
        raise RuntimeError("throttled")
    calls = []
    g = load_agent("release_review", "graph").build(call_tool=lambda t, a: calls.append(t) or "{}", ask_model=broken)
    out = g.invoke({"prompt": "Change C-9 skips tests."})
    assert out["answer"].startswith("ERROR") and "throttled" in out["answer"] and calls == []


def test_agent_imports_without_aws_or_environment(load_agent, monkeypatch):
    for name in ("HUB_REGION", "TOOL_GATEWAY_URL", "MODEL_ID", "AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)
    assert callable(load_agent("release_review").run)


def test_this_bundle_passes_the_scan_rules(tmp_path):
    (tmp_path / "agent.zip").write_bytes(bundle(FOLDER))
    out = tmp_path / "unpacked"
    submission_check.unpack(tmp_path / "agent.zip", out)
    assert submission_check.check_layout(out) == []
    assert submission_check.check_requirements(out) == []
    assert sorted(p.name for p in out.iterdir()) == ["agent.py", "graph.py", "hub_tools.py", "main.py", "requirements.txt"]


def test_application_passes_the_form_check():
    app = json.loads((FOLDER / "agent.json").read_text())
    assert validate(app, publish_agent._catalog_tools()) == []
