"""docs_adk: a Google ADK agent that is there from the start. Its one tool runs in its own process; the model is
Amazon Bedrock's Converse API through a small ADK model class. The ADK runner, the tool and the model class are real;
only the Bedrock client is a fake, so no test calls AWS."""
import importlib.metadata
import json
import pathlib
import re
import sys

import pytest
from botocore.exceptions import ClientError

from platform_team.agent_catalog.application_form import validate
from platform_team.agent_catalog.publish_agent import _catalog_tools, bundle
from platform_team.hosting_review import submission_check

ROOT = pathlib.Path(__file__).resolve().parents[1]
FOLDER = ROOT / "dev_team" / "preloaded_agents" / "docs_adk"
QUESTION = "What is our standard for versioning an API?"
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
TOOL_USE = {"toolUse": {"toolUseId": "tooluse-1", "name": "find_standard", "input": {"topic": "API versioning"}}}


class FakeBedrock:
    """bedrock-runtime's converse: gives the answers in turn (an exception instance is raised) and keeps each request."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def converse(self, **request):
        self.requests.append(json.loads(json.dumps(request)))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _says(*blocks, stop="end_turn"):
    """A Converse answer whose message holds these content blocks."""
    return {"output": {"message": {"role": "assistant", "content": list(blocks)}}, "stopReason": stop,
            "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}}


@pytest.fixture
def agent(load_agent, monkeypatch):
    monkeypatch.setenv("MODEL_ID", MODEL)
    monkeypatch.setenv("HUB_REGION", "us-west-2")
    return load_agent("preloaded_agents/docs_adk")


def _wire(agent, monkeypatch, *answers) -> FakeBedrock:
    """The agent talks to a fake Bedrock; a call of the hub's tool client fails the test."""
    bedrock = FakeBedrock(*answers)
    monkeypatch.setattr(agent, "_bedrock", lambda region: bedrock)
    monkeypatch.setattr(sys.modules["hub_tools"], "call_tool", lambda *a, **kw: pytest.fail("docs_adk called a hub tool"))
    return bedrock


def test_find_standard_gives_the_standard_of_a_topic_and_names_the_topics_there_are(agent):
    assert agent.find_standard("API versioning").startswith("STD-01 API versioning:")
    assert "/v1/" in agent.find_standard("How do we version an endpoint?")
    assert agent.find_standard("how long may an outbound call wait before a retry?").startswith("STD-03")
    assert agent.find_standard("what goes into a log line").startswith("STD-02")
    missing = agent.find_standard("the colour of the logo")
    assert missing.startswith("No design standard covers 'the colour of the logo'.")
    assert all(f"{s['title']} ({s['id']})" in missing for s in agent.STANDARDS) and len(agent.STANDARDS) == 3


def test_a_question_runs_the_adk_loop_with_the_tool_in_the_agents_own_process(agent, monkeypatch):
    bedrock = _wire(agent, monkeypatch, _says({"text": "Let me look."}, TOOL_USE, stop="tool_use"),
                    _says({"text": "STD-01: every public HTTP API carries its major version in the path."}))
    assert agent.run(QUESTION) == ("STD-01: every public HTTP API carries its major version in the path.",
                                   ["find_standard"])
    first, second = bedrock.requests
    assert first["messages"] == [{"role": "user", "content": [{"text": QUESTION}]}]
    assert second["messages"] == first["messages"] + [
        {"role": "assistant", "content": [{"text": "Let me look."}, TOOL_USE]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "tooluse-1",
                                                     "content": [{"text": agent.find_standard("API versioning")}]}}]}]


def test_the_model_request_names_the_hubs_model_the_instructions_and_the_tool(agent, monkeypatch):
    bedrock = _wire(agent, monkeypatch, _says({"text": "There is no standard for that."}))
    agent.run("What is our standard for colours?")
    [request] = bedrock.requests
    assert request["modelId"] == MODEL and request["inferenceConfig"] == {"maxTokens": 1000, "temperature": 0}
    assert request["system"][0]["text"].startswith(agent.INSTRUCTION) and len(request["system"]) == 1
    [tool] = request["toolConfig"]["tools"]
    assert tool["toolSpec"]["name"] == "find_standard"
    assert tool["toolSpec"]["description"].startswith("Find the company's design standard for a topic.")
    schema = tool["toolSpec"]["inputSchema"]["json"]
    assert (schema["type"], schema["required"], schema["properties"]["topic"]["type"]) == ("object", ["topic"], "string")


def test_each_question_starts_a_conversation_of_its_own(agent, monkeypatch):
    bedrock = _wire(agent, monkeypatch, _says({"text": "one"}), _says({"text": "two"}))
    assert agent.run("first question")[0] == "one" and agent.run("second question")[0] == "two"
    assert [len(r["messages"]) for r in bedrock.requests] == [1, 1]


def test_a_failure_is_told_to_the_caller_and_not_raised(agent, monkeypatch):
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "User: arn:aws:sts::123456789012:"
                                    "assumed-role/hub-agent-docs_adk-role/x is not authorized"}}, "Converse")
    _wire(agent, monkeypatch, denied)
    answer, used = agent.run(QUESTION)
    assert answer.startswith("ERROR: ClientError: An error occurred (AccessDeniedException)") and used == []
    assert "<ACCOUNT>" in answer and not re.search(r"[0-9]{12}", answer)
    assert agent.run("  ") == ("ERROR: empty prompt", [])
    monkeypatch.delenv("MODEL_ID")
    assert agent.run(QUESTION)[0] == "ERROR: KeyError: 'MODEL_ID'"


def test_the_application_names_no_hub_tool_and_passes_the_form_check():
    app = json.loads((FOLDER / "agent.json").read_text())
    assert {k: app[k] for k in ("name", "team", "framework", "tools")} == {
        "name": "docs_adk", "team": "common", "framework": "google-adk", "tools": []}
    assert app["description"].strip() and validate(app, _catalog_tools()) == []


def test_the_bundle_holds_the_agent_and_the_templates_files_and_passes_the_scan_rules(tmp_path):
    (tmp_path / "agent.zip").write_bytes(bundle(FOLDER))
    submission_check.unpack(tmp_path / "agent.zip", tmp_path / "src")
    assert sorted(p.name for p in (tmp_path / "src").iterdir()) == ["agent.py", "hub_tools.py", "main.py",
                                                                    "requirements.txt"]
    assert submission_check.check_layout(tmp_path / "src") == submission_check.check_requirements(tmp_path / "src") == []


def test_the_requirements_start_with_the_tracing_package_and_pin_the_adk_the_tests_run():
    lines = (FOLDER / "requirements.txt").read_text().splitlines()
    template = (ROOT / "dev_team/agent_template/requirements.txt").read_text().splitlines()
    assert lines[0] == "aws-opentelemetry-distro==0.24.0" and lines == sorted(lines) and set(template) <= set(lines)
    assert sorted(set(lines) - set(template)) == ["google-adk==2.14.1"]
    dev_group = re.search(r"^dev = \[(.*?)\]", (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert '"google-adk==2.14.1"' in dev_group and importlib.metadata.version("google-adk") == "2.14.1"
