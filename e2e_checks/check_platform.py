"""check_platform.py - check the platform frame that `make deploy seed` brought up, on real AWS.

    make deploy seed && AWS_REGION=us-west-2 uv run python e2e_checks/check_platform.py

Seven checks, one [PASS] / [FAIL] line each, then `== N checks passed, M failed`. Exit code 1 if any failed.
  1-2  the two gateways: READY, one policy engine in ENFORCE on both, no protocol type on the agent gateway
  3-5  as the dev team role, before any review: tools/list shows the shared read tool only; it answers; another tool is refused
  6    a catalog search as the dev team role finds the seeded shared tool record
  7    terraform plan -detailed-exitcode is 0: running again changes nothing
Printed output masks the account ID.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3

from platform_team.agent_catalog.catalog_records import search
from platform_team.agent_catalog.seed_catalog import SHARED_RECORD
from platform_team.agent_gateway.gateway_targets import find_gateway
from platform_team.sample_tools.tool_data import PARTS, TEST_RESULTS
from platform_team.sample_tools.tool_schema import SHARED_READ
from platform_team.shared_code.aws_helpers import Clients, mask, retry, signed_post
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import load

START_POINT = Path(__file__).resolve().parents[1] / "platform_team" / "terraform"
OTHER_TOOL = "Parts___get_test_result"
QUERY = "part specification tool"
RESULTS: list[tuple[str, bool]] = []
ACCOUNT = ""


def say(msg) -> None:
    print(mask(str(msg), ACCOUNT) if ACCOUNT else msg, flush=True)


def record(name: str, ok: bool, note: str) -> None:
    RESULTS.append((name, bool(ok)))
    say(f"[{'PASS' if ok else 'FAIL'}] {name}: {note}")


def as_json(text: str) -> dict:
    """The JSON body of an MCP answer; a streamed answer carries it on a data: line."""
    for line in text.splitlines():
        if line.startswith("data:"):
            text = line[5:].strip()
    try:
        doc = json.loads(text)
        return doc if isinstance(doc, dict) else {}
    except ValueError:
        return {}


def mcp(url: str, method: str, params: dict, region: str, creds) -> dict:
    _, body = signed_post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, region,
                          headers={"Accept": "application/json, text/event-stream"}, creds=creds)
    return as_json(body)


def dev_session(c: Clients, role_arn: str, region: str) -> boto3.Session:
    r = retry(lambda: c.sts.assume_role(RoleArn=role_arn, RoleSessionName="developer")["Credentials"])
    return boto3.Session(aws_access_key_id=r["AccessKeyId"], aws_secret_access_key=r["SecretAccessKey"],
                         aws_session_token=r["SessionToken"], region_name=region)


def check_gateways(s: Settings, c: Clients, engine_arn: str) -> None:
    agw, tgw = find_gateway(c, s.agent_gateway), find_gateway(c, s.tool_gateway)
    if not (agw and tgw):
        record("two gateways READY, one engine in ENFORCE", False, f"missing: {[n for n, g in ((s.agent_gateway, agw), (s.tool_gateway, tgw)) if not g]}")
        record("agent gateway has no protocol type", False, "agent gateway missing")
        return
    pe = {g["name"]: g.get("policyEngineConfiguration") or {} for g in (agw, tgw)}
    same = all(cfg.get("arn") == engine_arn and cfg.get("mode") == "ENFORCE" for cfg in pe.values())
    record("two gateways READY, one engine in ENFORCE", agw["status"] == tgw["status"] == "READY" and same,
           "; ".join(f"{g['name']} {g['status']} engine {pe[g['name']].get('arn', '-').rsplit('/', 1)[-1]} "
                     f"{pe[g['name']].get('mode')}" for g in (agw, tgw)))
    record("agent gateway has no protocol type", "protocolType" not in agw and tgw.get("protocolType") == "MCP",
           f"{agw['name']} protocolType {agw.get('protocolType', '<absent>')}; {tgw['name']} {tgw.get('protocolType')}")


def check_dev_tools(s: Settings, dev: boto3.Session, url: str) -> None:
    creds = dev.get_credentials().get_frozen_credentials()
    listed, t0 = [], time.monotonic()
    while time.monotonic() - t0 < 60:                 # a policy made seconds ago can take a moment to apply
        listed = sorted(t["name"] for t in (mcp(url, "tools/list", {}, s.region, creds).get("result") or {}).get("tools", []))
        if listed == sorted(SHARED_READ):
            break
        time.sleep(5)
    record("dev role sees the shared read tool only", listed == sorted(SHARED_READ), f"tools/list as the dev role: {listed}")
    ok = mcp(url, "tools/call", {"name": SHARED_READ[0], "arguments": {"part_id": "P-100"}}, s.region, creds)
    text = json.dumps(ok)
    record("the shared read tool answers", PARTS["P-100"]["spec"] in text and not (ok.get("result") or {}).get("isError"),
           f"{SHARED_READ[0]} -> {text[:160]}")
    no = mcp(url, "tools/call", {"name": OTHER_TOOL, "arguments": {"part_id": "P-100"}}, s.region, creds)
    refused = TEST_RESULTS["P-100"]["inspector_id"] not in json.dumps(no) and bool(no.get("error") or (no.get("result") or {}).get("isError"))
    record("another tool is refused", refused, f"{OTHER_TOOL} -> {json.dumps(no.get('error') or no.get('result'))[:160]}")


def check_search(dev: boto3.Session, registry_id: str) -> None:
    found, t0 = [], time.monotonic()
    while time.monotonic() - t0 < 120 and SHARED_RECORD not in found:      # the search index follows the approval
        found = search(Clients(dev), registry_id, QUERY)
        if SHARED_RECORD not in found:
            time.sleep(10)
    record("catalog search finds the shared tool", SHARED_RECORD in found,
           f"search {QUERY!r} as the dev role returned {found} after {time.monotonic() - t0:.0f}s")


def check_plan(s: Settings) -> None:
    env = {**os.environ, "TF_VAR_region": s.region, "TF_VAR_prefix": s.prefix, "TF_VAR_model_id": s.model_id}
    t0 = time.monotonic()
    r = subprocess.run(["terraform", f"-chdir={START_POINT}", "plan", "-detailed-exitcode", "-input=false", "-no-color",
                        "-lock-timeout=60s"], env=env, capture_output=True, text=True)
    changes = [line.strip() for line in r.stdout.splitlines() if line.strip().startswith("# ")]
    record("terraform plan shows no changes", r.returncode == 0,
           f"exit code {r.returncode} in {time.monotonic() - t0:.0f}s" + (f"; {changes or r.stderr.strip()[-300:]}" if r.returncode else ""))


def main() -> None:
    global ACCOUNT
    s = Settings.from_env()
    c = Clients.for_settings(s)
    ACCOUNT = c.account
    p = load(s, c)
    say(f"== check_platform ({s.region}, prefix {s.prefix})")
    t0 = time.monotonic()
    check_gateways(s, c, p.engine_arn)
    dev = dev_session(c, p.dev_role_arn, s.region)
    check_dev_tools(s, dev, p.tool_gw["url"])
    check_search(dev, p.registry_id)
    check_plan(s)
    failed = [name for name, ok in RESULTS if not ok]
    say(f"== {len(RESULTS) - len(failed)} checks passed, {len(failed)} failed" + (f": {failed}" if failed else "")
        + f" ({time.monotonic() - t0:.0f}s)")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                       # a traceback could print the account ID: mask it
        say(f"ERROR {type(e).__name__}: {e}")
        sys.exit(1)
