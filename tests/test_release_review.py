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
    assert calls[0][1] == {"change_id": "C-7", "summary": "canary stage skipped | Change C-7 skips the canary stage."}
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


def test_a_model_error_reaches_the_caller_without_the_account(load_agent):      # final review M-5
    def denied(system, user):
        raise RuntimeError("User: arn:aws:sts::123456789012:assumed-role/hub-agent-release_review-role/s is not "
                           "authorized to perform: bedrock:InvokeModel " + "x" * 1000)
    g = load_agent("release_review", "graph").build(call_tool=lambda t, a: "{}", ask_model=denied)
    answer = g.invoke({"prompt": "Change C-9 skips tests."})["answer"]
    assert answer.startswith("ERROR: the model could not check the rules: RuntimeError: User: arn:aws:sts::<ACCOUNT>:")
    assert "123456789012" not in answer and len(answer) < 400


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


import pytest


@pytest.mark.parametrize("verdict", ["Violation: no canary", " \nVIOLATION: no canary", "**VIOLATION**: no canary", "`violation`: no canary"])
def test_a_violation_is_read_whatever_its_case_or_markup(load_agent, verdict):
    out, calls = run(load_agent, "Change C-7 skips the canary stage.", verdict)
    assert len(calls) == 1 and "RR-1" in out["answer"]
    assert calls[0][1]["summary"].startswith("no canary")


@pytest.mark.parametrize("verdict", ["No VIOLATION found", "I think this is fine.", "", "Sure! VIOLATION: x"])
def test_an_unclear_answer_is_an_error_not_a_pass_or_a_violation(load_agent, verdict):
    out, calls = run(load_agent, "Change C-7 skips the canary stage.", verdict)
    assert calls == [] and out["answer"].startswith("ERROR: unexpected model answer")


def test_ok_with_spaces_is_a_pass(load_agent):
    out, calls = run(load_agent, "Change C-8 is fine.", " OK\n")
    assert calls == [] and out["answer"] == "OK"


@pytest.mark.parametrize("prompt", ["", "   \n"])
def test_a_blank_description_is_refused_without_asking_the_model(load_agent, prompt):
    asked = []
    g = load_agent("release_review", "graph").build(call_tool=lambda t, a: "{}", ask_model=lambda s, u: asked.append(u) or "OK")
    out = g.invoke({"prompt": prompt})
    assert out["answer"] == "ERROR: empty change description" and asked == []


def test_the_change_id_after_the_word_change_wins(load_agent):
    _, calls = run(load_agent, "See TICKET-1 first. Change C-7 skips the canary stage.", "VIOLATION: x")
    assert calls[0][1]["change_id"] == "C-7"


def test_without_the_word_change_the_first_id_is_used_and_without_any_it_is_unknown(load_agent):
    _, calls = run(load_agent, "Release R-12 skips canary.", "VIOLATION: x")
    assert calls[0][1]["change_id"] == "R-12"
    _, calls = run(load_agent, "A rollout skips canary.", "VIOLATION: x")
    assert calls[0][1]["change_id"] == "unknown"


def test_the_summary_carries_the_reason_and_a_trimmed_description(load_agent):
    _, calls = run(load_agent, "Change C-7 " + "x" * 300, "VIOLATION: no canary")
    assert calls[0][1]["summary"] == "no canary | Change C-7 " + "x" * 89


def test_a_tool_answer_that_is_not_json_is_a_failure_to_file(load_agent):
    out, _ = run(load_agent, "Change C-7 skips the canary stage.", "VIOLATION: x", "<html>oops</html>")
    assert "could not be filed" in out["answer"] and "Review request:" not in out["answer"]
