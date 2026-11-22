import json, subprocess, sys, zipfile
from platform_team.shared_code.code_package import build

BUNDLED = ("platform_team.sample_tools.tool_handler", "platform_team.shared_code.aws_helpers",
           "platform_team.company_policy.policy_engine", "platform_team.agent_gateway.gateway_targets",
           "platform_team.agent_catalog.catalog_records", "platform_team.hosting_review.submission_check",
           "platform_team.hosting_review.deploy_build", "platform_team.custom_guardrail.interceptor_lambda")

def test_the_package_needs_only_the_standard_library_and_what_it_carries(tmp_path):
    build(tmp_path)
    code = "import importlib, sys; sys.path.insert(0, sys.argv[1]); [importlib.import_module(m) for m in sys.argv[2:]]"
    r = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(tmp_path / "platform_team.zip"), *BUNDLED],
                       capture_output=True, text=True)       # -I -S: no site-packages, no current folder
    assert r.returncode == 0, r.stderr[-1500:]

def test_package_holds_the_hub_code_boto3_and_the_tool_schemas(tmp_path):
    out = build(tmp_path)
    names = zipfile.ZipFile(tmp_path / "platform_team.zip").namelist()
    assert "platform_team/sample_tools/tool_handler.py" in names and "platform_team/shared_code/config.py" in names
    assert "platform_team/company_policy/policy_templates/tool-permit.cedar" in names
    assert "platform_team/hosting_review/deploy_build.py" in names                         # the deploy build runs it
    assert not any(n.startswith("platform_team/hosting_review/runtime_skeleton/") for n in names)
    assert not any(n.endswith(".tf") for n in names)
    assert any(n.startswith("boto3/") for n in names) and any(n.startswith("botocore/data/bedrock-agentcore-control/") for n in names)
    assert not any(n.startswith("botocore/data/ec2/") for n in names)           # unused API models are dropped
    schemas = json.loads((tmp_path / "tool_schemas.json").read_text())
    assert sorted(schemas) == ["Parts", "Quality", "Release"] and out["zip"].endswith("platform_team.zip")

def test_the_interceptor_can_make_its_amazon_bedrock_client_from_the_package_alone(tmp_path):
    """The interceptor calls ApplyGuardrail (bedrock-runtime); the cleanup check lists guardrails (bedrock)."""
    build(tmp_path)
    names = zipfile.ZipFile(tmp_path / "platform_team.zip").namelist()
    assert "platform_team/custom_guardrail/interceptor_lambda.py" in names
    assert any(n.startswith("botocore/data/bedrock-runtime/") for n in names) and any(n.startswith("botocore/data/bedrock/") for n in names)
    zipfile.ZipFile(tmp_path / "platform_team.zip").extractall(tmp_path / "task")     # Lambda runs the zip unpacked
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import boto3; "
            "c = boto3.client('bedrock-runtime', region_name='us-west-2', aws_access_key_id='a', aws_secret_access_key='b'); "
            "assert c.meta.service_model.operation_model('ApplyGuardrail')")
    r = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(tmp_path / "task")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
