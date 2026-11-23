"""The names the hub makes from an agent's name: one kind, one agent and one tool per policy name, and every name
fits its limit, or the application is refused before anything is made."""
import itertools
import json
import pathlib
import re

import pytest

from platform_team.agent_catalog import publish_agent
from platform_team.agent_catalog.application_form import TOOL_PATTERN, validate
from platform_team.company_policy import policy_names as names
from platform_team.hosting_review import review_steps as steps
from platform_team.sample_tools.tool_schema import TARGETS
from platform_team.shared_code.config import Settings
from tests.fakes import ENV, SPEC, FakeClients, read_input

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = {f"{target}___{t['name']}" for target, tools in TARGETS.items() for t in tools}
APP = {"name": "quality_agent", "team": "appliance", "framework": "strands", "tools": ["Parts___get_part_spec"]}


def test_no_kind_prefix_is_a_prefix_of_another():
    prefixes = list(names.KINDS.values())
    assert len(prefixes) == len(set(prefixes)) >= 6
    assert [(a, b) for a, b in itertools.permutations(prefixes, 2) if b.startswith(a)] == []


def test_the_policy_names_are_the_ruled_ones():
    assert names.policy_names("quality_agent", ["Quality___get_inspection_data", "Parts___get_part_spec"]) == [
        "entry_permit_quality_agent", "review_permit_quality_agent", "tool_quality_agent_Parts_get_part_spec",
        "tool_quality_agent_Quality_get_inspection_data", "guard_secret_quality_agent", "guard_prompt_quality_agent",
        "stop_agent_quality_agent"]


def test_cleanup_removes_the_entry_permit_first_and_the_stop_policy_last():
    found = names.policy_names("quality_agent", ["Parts___get_part_spec"])
    assert found[0] == "entry_permit_quality_agent"
    assert found[-2:] == ["guard_prompt_quality_agent", "stop_agent_quality_agent"]


def test_names_of_different_agents_kinds_and_tools_never_meet():
    agents = ["quality", "quality_agent", "review_quality", "review", "permit", "tool", "entry", "entry_permit",
              "guard", "secret", "agent", "parts", "ab_c", "a_bc", "abc"]
    made = [(n, a) for a in agents for n in names.policy_names(a, sorted(CATALOG))]
    assert len({n for n, _ in made}) == len(made)


def test_the_tool_permit_pattern_finds_one_agents_permits_and_no_others():     # the cleanup uses it
    agents = ["quality", "quality_agent", "review_quality", "review", "permit", "tool", "entry", "entry_permit",
              "guard", "secret", "agent", "parts", "ab_c", "a_bc", "abc"]
    made = {a: names.policy_names(a, sorted(CATALOG)) for a in agents}
    for agent in agents:
        pattern = re.compile(names.tool_policy_pattern(agent))
        found = {n for a in agents for n in made[a] if pattern.fullmatch(n)}
        assert found == {names.tool_policy_name(agent, t) for t in CATALOG}, agent
    assert re.fullmatch(names.tool_policy_pattern("quality_agent"), "tool_quality_agent_Retired_get_old_data")


def test_catalog_targets_start_upper_case_and_hold_no_underscore():
    assert all(re.fullmatch(r"[A-Z][A-Za-z0-9]*", target) for target in TARGETS)
    assert all(re.fullmatch(TOOL_PATTERN, tool) for tool in CATALOG)


@pytest.mark.parametrize("tool", ["parts___get_part_spec", "Pa_rts___get_part_spec", "Parts__get_part_spec"])
def test_a_tool_whose_target_is_not_one_word_starting_upper_case_is_refused(tool):
    assert f"tool must look like <Target>___<tool>: {tool}" in validate({**APP, "tools": [tool]}, CATALOG | {tool})


@pytest.mark.parametrize("name", ["agent_1", "quality__agent", "quality_", "_quality", "Quality", "qa", "a" * 32, "1abc"])
def test_an_agent_name_that_is_not_lower_case_segments_is_refused(name):
    assert any(p.startswith("name must") for p in validate({**APP, "name": name}, CATALOG))


def test_valid_agent_names_give_one_to_one_runtime_and_target_names():
    s, valid = Settings(), ["ab_c", "a_bc", "abc", "agent1", "quality_agent", "quality"]
    assert all(validate({**APP, "name": n}, CATALOG) == [] for n in valid)
    assert len({s.runtime_name(n) for n in valid}) == len({s.target_name(n) for n in valid}) == len(valid)
    assert (s.target_name("ab_c"), s.target_name("a_bc")) == ("AbC", "ABc")


def test_every_example_application_passes_the_form_check():
    forms = sorted([*(ROOT / "dev_team").glob("*/agent.json"), *(ROOT / "dev_team").glob("preloaded_agents/*/agent.json")])
    assert len(forms) >= 5
    for form in forms:
        app = json.loads(form.read_text())
        assert validate(app, CATALOG) == [], form.parent.name
        assert all(len(n) <= names.MAX_POLICY_NAME for n in names.policy_names(app["name"], app["tools"]))


def test_a_policy_name_over_the_limit_is_refused_with_the_room_the_agent_name_has():
    problems = validate({**APP, "name": "inspection_helper", "tools": ["Quality___get_inspection_data"]}, CATALOG)
    assert problems == ["policy name tool_inspection_helper_Quality_get_inspection_data has 50 characters; a policy "
                        "name may have at most 48, so for this policy the agent name may have at most 15 characters"]


def test_a_name_the_cli_refused_as_too_long_is_valid_now():
    assert validate({**APP, "name": "abcdefghij_klmnopqrstu"}, CATALOG) == []       # 22 characters, Runtime name 26


def test_read_refuses_a_name_that_does_not_fit_before_grant_makes_anything():
    c = FakeClients(record_spec={**SPEC, "name": "inspection_helper"})
    with pytest.raises(ValueError, match="policy name tool_inspection_helper_Quality_get_inspection_data has 50"):
        steps.read(read_input({"detail": {"registryId": "r", "registryRecordId": "x"}}), c, ENV)
    assert c.created_policies == [] and c.roles == {}


def test_publish_refuses_a_name_that_does_not_fit_before_uploading(tmp_path, monkeypatch):
    folder = tmp_path / "team_agent"
    folder.mkdir()
    (folder / "main.py").write_text("m")
    (folder / "requirements.txt").write_text("boto3==1.44.9\n")
    (folder / "agent.json").write_text(json.dumps({**APP, "name": "inspection_helper",
                                                   "tools": ["Quality___get_inspection_data"]}))
    c = FakeClients()
    monkeypatch.setattr(publish_agent, "load", lambda s, c=None: pytest.fail("publish read the hub before the check"))
    with pytest.raises(ValueError, match="a policy name may have at most 48"):
        publish_agent.publish(folder, Settings(), c=c)
