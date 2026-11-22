import re, types
from platform_team.sample_tools.tool_handler import handler
from platform_team.sample_tools.tool_schema import TARGETS, SHARED_READ

def ctx(tool):
    return types.SimpleNamespace(client_context=types.SimpleNamespace(custom={"bedrockAgentCoreToolName": tool}))

def test_schema_matches_the_design_table():
    assert {t: [x["name"] for x in tools] for t, tools in TARGETS.items()} == {
        "Quality": ["get_inspection_data"], "Parts": ["get_part_spec", "get_test_result"], "Release": ["file_review_request"]}
    assert SHARED_READ == ["Parts___get_part_spec"]

def test_inspection_data_carries_an_employee_id_and_one_pending_case():
    a = handler({"case_id": "Q-1001"}, ctx("Quality___get_inspection_data"))
    assert re.fullmatch(r"EMP-\d{6}", a["inspector_id"]) and a["synthetic"] is True
    assert handler({"case_id": "Q-1002"}, ctx("Quality___get_inspection_data"))["result"] == "PENDING"

def test_tools_are_stateless():
    r1 = handler({"change_id": "C-7", "summary": "x"}, ctx("Release___file_review_request"))
    r2 = handler({"change_id": "C-7", "summary": "x"}, ctx("Release___file_review_request"))
    assert r1 == r2 and r1["request_id"].startswith("RR-")

def test_unknown_tool_and_unknown_id_return_an_error_field():
    assert "error" in handler({}, ctx("Parts___nope"))
    assert "error" in handler({"part_id": "P-999"}, ctx("Parts___get_part_spec"))

def test_error_responses_are_marked_synthetic():
    assert handler({}, ctx("Parts___nope"))["synthetic"] is True
    assert handler({"part_id": "P-999"}, ctx("Parts___get_part_spec"))["synthetic"] is True

def test_file_review_request_needs_change_id_and_summary():
    assert "error" in handler({"summary": "x"}, ctx("Release___file_review_request"))
    assert "error" in handler({"change_id": "C-7"}, ctx("Release___file_review_request"))

def test_missing_tool_name_returns_an_error():
    expected = {"error": "missing tool name", "synthetic": True}
    assert handler({}, types.SimpleNamespace(client_context=None)) == expected
    assert handler({}, types.SimpleNamespace(client_context=types.SimpleNamespace(custom={}))) == expected
    assert handler({}, types.SimpleNamespace()) == expected

def test_tool_must_belong_to_its_target():
    assert "error" in handler({"case_id": "Q-1001"}, ctx("Parts___get_inspection_data"))
    assert "error" in handler({"case_id": "Q-1001"}, ctx("get_inspection_data"))
