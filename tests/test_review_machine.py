# tests/test_review_machine.py
import json, pathlib, re

def render():
    text = pathlib.Path("platform_team/hosting_review/terraform/review_machine.asl.json.tftpl").read_text()
    return json.loads(re.sub(r"\$\{(\w+)\}", lambda m: "x-" + m.group(1), text))
D = render()

def test_steps_run_in_the_design_order_on_the_right_service():
    order, state = [], D["StartAt"]
    while state in D["States"] and state != "Notify":
        st = D["States"][state]
        if st["Type"] == "Choice":                 # Reviewable: a record the review hosts goes on (Default)
            state = st["Default"]
            continue
        if st["Type"] != "Task":
            break
        order.append((state, "codebuild" if "codebuild" in st["Resource"] else "lambda"))
        state = st.get("Next")
    assert order == [("Read", "lambda"), ("Scan", "codebuild"), ("Grant", "lambda"), ("Deploy", "codebuild"),
                     ("Entry", "lambda"), ("TestCall", "lambda"), ("Approve", "lambda")]

def test_every_step_fails_into_the_notification():
    for name in ("Read", "Scan", "Grant", "Deploy", "Entry", "TestCall", "Approve"):
        assert D["States"][name]["Catch"] == [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error",
                                               "Assign": {"failedStep": name}, "Next": "Notify"}]
    assert D["States"]["Notify"]["Resource"] == "arn:aws:states:::sns:publish" and D["States"]["Notify"]["Next"] == "Failed"

def test_the_build_steps_wait_and_get_the_exact_code_version():
    scan = D["States"]["Scan"]
    assert scan["Resource"] == "arn:aws:states:::codebuild:startBuild.sync"
    env = {e["Name"]: e["Value.$"] for e in scan["Parameters"]["EnvironmentVariablesOverride"]}
    assert env == {"AGENT": "$.spec.name", "CODE_KEY": "$.spec.code_key", "CODE_VERSION": "$.spec.code_version"}
    deploy_env = {e["Name"] for e in D["States"]["Deploy"]["Parameters"]["EnvironmentVariablesOverride"]}
    assert deploy_env == {"AGENT", "CODE_KEY", "CODE_VERSION", "ROLE_ARN"}

# ------------------------------------------------------------------ found on AWS (Task 12)

def test_the_alert_names_the_step_that_failed():
    # On AWS the alert of a failed Scan had the subject "Hosting review failed" and the review's state: the agent
    # (spec.name) and a generic error (States.TaskFailed with the build record). Nothing named the step. Each Catch
    # remembers its step in the variable failedStep (above); the subject and the message carry it.
    p = D["States"]["Notify"]["Parameters"]
    assert p["Subject.$"] == "States.Format('Hosting review failed at {}', $failedStep)"
    assert "$failedStep" in p["Message.$"] and "States.JsonMerge(" in p["Message.$"] and p["Message.$"].count(", $, ") == 1
    # the alert names no field of the review's state: a failed Read has no spec yet, and its alert must still go out
    assert "$." not in json.dumps(p)

# ------------------------------------------------------------------ a record the review skips; the alert's retry

def test_a_skipped_record_ends_without_an_alert():
    # Read returns {"skip": <reason>} for a record the review does not host (a shared tool, a harness)
    assert D["States"]["Read"]["Next"] == "Reviewable"
    choice = D["States"]["Reviewable"]
    assert choice["Type"] == "Choice" and choice["Default"] == "Scan"
    assert choice["Choices"] == [{"Variable": "$.skip", "IsPresent": True, "Next": "Skipped"}]
    assert D["States"]["Skipped"]["Type"] == "Succeed"
    leads_to_notify = [n for n, st in D["States"].items() if st.get("Next") == "Notify"]
    assert leads_to_notify == []                                # only a Catch reaches the alert

def test_notify_retries_before_it_gives_up():
    retries = [r for r in D["States"]["Notify"].get("Retry", []) if "States.TaskFailed" in r["ErrorEquals"]]
    assert len(retries) == 1 and retries[0]["MaxAttempts"] >= 3 and retries[0]["IntervalSeconds"] >= 1

def test_each_lambda_state_waits_longer_than_its_function_may_run():
    # a state's TimeoutSeconds below its Lambda's timeout would end the review while the step still runs
    main = pathlib.Path("platform_team/hosting_review/terraform/main.tf").read_text()
    body = re.search(r"\n  steps = {(.*?)\n  }", main, re.S).group(1)
    timeout = {k: int(v) for k, v in re.findall(r"(\w+)\s*=\s*(\d+)", body)}
    states = {"Read": "read", "Grant": "grant", "Entry": "entry", "TestCall": "testcall", "Approve": "approve"}
    assert [s for s, step in states.items() if D["States"][s]["TimeoutSeconds"] <= timeout[step]] == []
    assert timeout["approve"] == 900                    # the company policies and the entry permit

# ------------------------------------------------------------------ the review of a new version

def test_read_gets_the_event_its_own_execution_and_the_state_machine():
    # Read stops a review of a record whose earlier review still runs: it needs to know which execution it is
    assert D["States"]["Read"]["Parameters"] == {"FunctionName": "x-fn_read", "Payload": {
        "event.$": "$", "execution.$": "$$.Execution.Id", "machine.$": "$$.StateMachine.Id"}}
    for name in ("Grant", "Entry", "TestCall", "Approve"):              # the later steps get the state as it is
        assert D["States"][name]["Parameters"]["Payload.$"] == "$"
