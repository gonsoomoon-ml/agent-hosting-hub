"""The scene command that searches the catalog: for the approved records that match, the name, the type and the
description, and for a tool its input fields. Nothing calls AWS: FakeClients stands in."""
import json

import pytest

from platform_team.agent_catalog import search_catalog
from platform_team.sample_tools.tool_schema import TARGETS
from tests.fakes import ACCOUNT, PLATFORM, FakeClients


def _record(name, kind, description, status, payload):
    return {"name": name, "recordId": f"rec-{name}", "recordType": kind, "status": status, "description": description,
            "descriptors": {"custom": {"data": json.dumps(payload)}}}


@pytest.fixture
def wired(monkeypatch):
    def wire(**kw):
        fake = FakeClients(record_status=None, **kw)       # no quality_agent record unless a test asks for it
        monkeypatch.setattr(search_catalog, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: fake)}))
        monkeypatch.setattr(search_catalog, "load", lambda s, c: PLATFORM)
        return fake
    return wire


def test_search_prints_name_type_and_description_of_approved_records(wired, capsys):
    fake = wired()
    fake.other_records += [
        _record("release_review", "AGENT", "Checks a change description against the release rules.", "APPROVED",
                {"name": "release_review"}),
        _record("old_review", "AGENT", "An older release rules review.", "PENDING_APPROVAL", {"name": "old_review"}),
        _record("parts-tools", "MCP", "Shared in-house tools for part data.", "APPROVED",
                {"target": "Parts", "tools": TARGETS["Parts"]})]
    assert search_catalog.main(["release rules review"]) == 0
    out = capsys.readouterr().out
    assert "release_review" in out and "AGENT" in out and "Checks a change description against the release rules." in out
    assert "old_review" not in out                                       # not approved: a search does not find it
    assert "parts-tools" not in out                                      # does not match the query


def test_search_prints_a_tools_input_fields(wired, capsys):
    fake = wired()
    fake.other_records.append(_record("parts-tools", "MCP", "Shared in-house tools for part data.", "APPROVED",
                                      {"target": "Parts", "tools": TARGETS["Parts"]}))
    assert search_catalog.main(["part data tools"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any("parts-tools" in x and "MCP" in x for x in lines)
    assert any("get_part_spec" in x and "part_id" in x for x in lines)
    assert any("get_test_result" in x and "part_id" in x for x in lines)


def test_search_reads_the_record_when_the_search_result_has_no_descriptors(wired, capsys):
    fake = wired()
    fake.search_descriptors = False
    fake.other_records.append(_record("parts-tools", "MCP", "Shared in-house tools for part data.", "APPROVED",
                                      {"target": "Parts", "tools": TARGETS["Parts"]}))
    assert search_catalog.main(["part data tools"]) == 0
    assert "get_part_spec" in capsys.readouterr().out
    assert fake.calls.count(("reg", "get_registry_record")) == 2       # the fake's own read for the item, and the command's


def test_search_does_not_read_the_record_again_when_the_search_result_has_its_descriptors(wired, capsys):
    fake = wired()
    fake.other_records.append(_record("parts-tools", "MCP", "Shared in-house tools for part data.", "APPROVED",
                                      {"target": "Parts", "tools": TARGETS["Parts"]}))
    assert search_catalog.main(["part data tools"]) == 0
    assert fake.calls.count(("reg", "get_registry_record")) == 1       # only the fake's own read for the item


def test_search_says_so_when_nothing_matches(wired, capsys):
    wired()
    assert search_catalog.main(["weather forecast"]) == 0
    assert capsys.readouterr().out.strip() == 'no approved record matches "weather forecast"'


def test_search_masks_the_account(wired, capsys):
    fake = wired()
    fake.other_records.append(_record("acct_agent", "AGENT", f"Runs in account {ACCOUNT}.", "APPROVED", {"name": "acct_agent"}))
    assert search_catalog.main(["acct_agent"]) == 0
    out = capsys.readouterr().out
    assert ACCOUNT not in out and "<ACCOUNT>" in out


@pytest.mark.parametrize("argv", [[], ["a", "b"], [""], ["   "]])
def test_search_exits_2_for_bad_usage(wired, capsys, argv):
    fake = wired()
    assert search_catalog.main(argv) == 2
    assert capsys.readouterr().out.startswith("usage: ") and fake.calls == []


def test_search_says_in_one_line_when_the_hub_is_not_deployed(wired, monkeypatch, capsys):
    wired()
    from platform_team.shared_code.hub_state import NotDeployed
    monkeypatch.setattr(search_catalog, "load", lambda s, c: (_ for _ in ()).throw(NotDeployed("run `make deploy` first")))
    assert search_catalog.main(["x y"]) == 1
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "make deploy" in out
