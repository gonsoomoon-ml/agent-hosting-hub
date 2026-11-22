# tests/test_review_machine.py
import json, pathlib, re

def render():
    text = pathlib.Path("platform_team/hosting_review/terraform/review_machine.asl.json.tftpl").read_text()
    return json.loads(re.sub(r"\$\{(\w+)\}", lambda m: "x-" + m.group(1), text))
D = render()

def test_steps_run_in_the_design_order_on_the_right_service():
    order, state = [], D["StartAt"]
    while state in D["States"] and D["States"][state]["Type"] == "Task" and state != "Notify":
        st = D["States"][state]
        order.append((state, "codebuild" if "codebuild" in st["Resource"] else "lambda"))
        state = st.get("Next")
    assert order == [("Read", "lambda"), ("Scan", "codebuild"), ("Grant", "lambda"), ("Deploy", "codebuild"),
                     ("Entry", "lambda"), ("TestCall", "lambda"), ("Approve", "lambda")]

def test_every_step_fails_into_the_notification():
    for name in ("Read", "Scan", "Grant", "Deploy", "Entry", "TestCall", "Approve"):
        assert D["States"][name]["Catch"] == [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Notify"}]
    assert D["States"]["Notify"]["Resource"] == "arn:aws:states:::sns:publish" and D["States"]["Notify"]["Next"] == "Failed"

def test_the_build_steps_wait_and_get_the_exact_code_version():
    scan = D["States"]["Scan"]
    assert scan["Resource"] == "arn:aws:states:::codebuild:startBuild.sync"
    env = {e["Name"]: e["Value.$"] for e in scan["Parameters"]["EnvironmentVariablesOverride"]}
    assert env == {"AGENT": "$.spec.name", "CODE_KEY": "$.spec.code_key", "CODE_VERSION": "$.spec.code_version"}
    deploy_env = {e["Name"] for e in D["States"]["Deploy"]["Parameters"]["EnvironmentVariablesOverride"]}
    assert deploy_env == {"AGENT", "CODE_KEY", "CODE_VERSION", "ROLE_ARN"}
