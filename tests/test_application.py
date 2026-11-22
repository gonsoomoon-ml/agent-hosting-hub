from platform_team.agent_catalog.application_form import validate
CATALOG = {"Parts___get_part_spec", "Quality___get_inspection_data", "Release___file_review_request"}
OK = {"name": "quality_agent", "team": "appliance", "framework": "strands", "tools": ["Parts___get_part_spec"]}

def test_valid_application_has_no_problems():
    assert validate(OK, CATALOG) == []

def test_unknown_tool_is_reported():          # Review Focus 3
    problems = validate({**OK, "tools": ["Parts___get_part_spec", "Parts___delete_everything"]}, CATALOG)
    assert problems == ["tool not in the catalog: Parts___delete_everything"]

def test_missing_keys_and_bad_name_are_reported():
    assert validate({"name": "Bad Name", "tools": []}, CATALOG) == [
        "missing: team", "missing: framework", "name must match ^[a-z][a-z0-9]*(_[a-z][a-z0-9]*)*$", "tools must not be empty"]
