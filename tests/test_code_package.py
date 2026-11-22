import json, zipfile
from platform_team.shared_code.code_package import build

def test_package_holds_the_hub_code_boto3_and_the_tool_schemas(tmp_path):
    out = build(tmp_path)
    names = zipfile.ZipFile(tmp_path / "platform_team.zip").namelist()
    assert "platform_team/sample_tools/tool_handler.py" in names and "platform_team/shared_code/config.py" in names
    assert "platform_team/company_policy/policy_templates/tool-permit.cedar" in names
    assert not any(n.endswith(".tf") for n in names)
    assert any(n.startswith("boto3/") for n in names) and any(n.startswith("botocore/data/bedrock-agentcore-control/") for n in names)
    assert not any(n.startswith("botocore/data/ec2/") for n in names)           # unused API models are dropped
    schemas = json.loads((tmp_path / "tool_schemas.json").read_text())
    assert sorted(schemas) == ["Parts", "Quality", "Release"] and out["zip"].endswith("platform_team.zip")
