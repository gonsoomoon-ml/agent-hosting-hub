from platform_team.agent_catalog.application_form import validate
CATALOG = {"Parts___get_part_spec", "Quality___get_inspection_data", "Release___file_review_request"}
OK = {"name": "quality_agent", "team": "appliance", "framework": "strands", "tools": ["Parts___get_part_spec"]}

def test_valid_application_has_no_problems():
    assert validate(OK, CATALOG) == []

def test_unknown_tool_is_reported():          # Review Focus 3
    problems = validate({**OK, "tools": ["Parts___get_part_spec", "Parts___delete_everything"]}, CATALOG)
    assert problems == ["tool not in the catalog: Parts___delete_everything"]

def test_missing_keys_and_bad_name_are_reported():
    assert validate({"name": "Bad Name"}, CATALOG) == [
        "missing: team", "missing: framework", "missing: tools", "name must match ^[a-z][a-z0-9]*(_[a-z][a-z0-9]*)*$"]

def test_an_application_may_name_no_hub_tool():
    """An agent whose tools run in its own process calls no tool through the hub: its list of hub tools is empty."""
    assert validate({"name": "docs_adk", "team": "common", "framework": "google-adk", "tools": []}, CATALOG) == []

# final review I-1: publish refuses the same shapes as the review's Read

def test_tools_that_are_not_a_list_are_reported_once():
    for tools in ("Parts___get_part_spec", {"Parts___get_part_spec": 1}, 3):
        assert validate({**OK, "tools": tools}, CATALOG) == ["tools must be a list of tool names"], tools

def test_team_and_framework_must_be_short_strings():
    for field in ("team", "framework"):
        for value in (5, ["x"], "", "x" * 65, None):
            assert validate({**OK, field: value}, CATALOG) == [f"{field} must be a string of 1 to 64 characters"], value
        assert validate({**OK, field: "x" * 64}, CATALOG) == []
