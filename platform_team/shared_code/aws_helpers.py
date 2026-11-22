"""Shared AWS helpers: one boto3 session with named clients, retry, status waits and their deadline, SigV4 calls."""
import json
import math
import time
import urllib.error
import urllib.request
from functools import cached_property

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.exceptions import ClientError

from platform_team.shared_code.config import Settings

# attribute name -> boto3 service name
_SERVICES = {
    "iam": "iam", "s3": "s3", "lam": "lambda", "sts": "sts", "ssm": "ssm", "sns": "sns", "sqs": "sqs",
    "sfn": "stepfunctions", "events": "events", "codebuild": "codebuild", "cw": "cloudwatch", "logs": "logs",
    "ctl": "bedrock-agentcore-control", "data": "bedrock-agentcore",
    "reg": "agent-registry-control", "disc": "agent-registry",
}


class Clients:
    """boto3 clients for one region. Clients are created on first use; nothing calls AWS at import time."""

    def __init__(self, session: boto3.Session):
        self.session = session
        self._clients: dict = {}

    @classmethod
    def for_settings(cls, s: Settings) -> "Clients":
        return cls(boto3.Session(region_name=s.region))

    def __getattr__(self, name: str):
        service = _SERVICES.get(name)
        if service is None:
            raise AttributeError(name)
        if name not in self._clients:
            self._clients[name] = self.session.client(service)
        return self._clients[name]

    @cached_property
    def account(self) -> str:
        return self.sts.get_caller_identity()["Account"]


def mask(text: str, account: str) -> str:
    return text.replace(account, "<ACCOUNT>")


def items(resp: dict) -> list:
    """The list inside a List* response, whatever its key is called."""
    return next((v for v in resp.values() if isinstance(v, list)), [])


def all_items(call, **kwargs) -> list:
    """Every item of a List* call, page by page (nextToken)."""
    out, token = [], None
    while True:
        resp = call(**kwargs, **({"nextToken": token} if token else {}))
        out += items(resp)
        token = resp.get("nextToken")
        if not token:
            return out


def already_exists(err: ClientError) -> bool:
    """A step that runs again keeps what it made before."""
    e = err.response["Error"]
    return e["Code"] in ("ConflictException", "ResourceAlreadyExistsException") or "already exists" in e["Message"]


def retry(fn, tries=8, wait=10, on=("ClientError",)):
    """Call fn until it works. Roles created seconds ago are not always usable yet.
    `on` lists the exception class names that are worth another try."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if type(e).__name__ not in on or i == tries - 1:
                raise
            time.sleep(wait)


class OutOfTime(RuntimeError):
    """A step has no time left for its next wait, so it stops with this message instead of a Lambda timeout."""


class Deadline:
    """When a step must be done (the Lambda handler sets it a margin before the Lambda timeout). Each wait takes
    its normal ceiling or the time left, whichever is shorter. Deadline() has no end: every wait gets its ceiling."""

    def __init__(self, seconds: float | None = None):
        self.end = None if seconds is None else time.monotonic() + seconds

    def left(self) -> float:
        return float("inf") if self.end is None else self.end - time.monotonic()

    def wait(self, ceiling: float, what: str) -> float:
        """How long the next wait may take. Less than a second left raises OutOfTime, before anything is made."""
        if self.end is None:
            return ceiling
        left = self.left()
        if left < 1:
            raise OutOfTime(f"no time left for {what}: the step stops before its Lambda timeout")
        return min(ceiling, math.floor(left))


def wait_status(read, want: tuple[str, ...], what: str, timeout=300, step=4) -> dict:
    """Poll read() until its status is in `want`. A status ending in FAILED raises RuntimeError."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        cur = read()
        if cur["status"] in want:
            return cur
        if cur["status"].endswith("FAILED"):
            reasons = cur.get("statusReasons") or cur.get("statusReason")
            raise RuntimeError(f"{what} {cur['status']}: {reasons}")
        time.sleep(step)
    raise TimeoutError(f"{what} not {want} within {timeout}s")


def signed_post(url: str, body: dict, region: str, headers: dict | None = None, creds=None, timeout=180) -> tuple[int, str]:
    """POST a JSON body signed with SigV4 for the bedrock-agentcore service. Returns (status, text).
    An HTTP error status is returned, not raised; network errors and timeouts are raised.
    Standard library only (urllib), so the hub's code package carries no HTTP client."""
    raw = json.dumps(body)
    h = {"Content-Type": "application/json", **(headers or {})}
    signed = AWSRequest(method="POST", url=url, data=raw, headers=h)
    creds = creds or boto3.Session(region_name=region).get_credentials().get_frozen_credentials()
    SigV4Auth(creds, "bedrock-agentcore", region).add_auth(signed)
    req = urllib.request.Request(url, data=raw.encode(), headers=dict(signed.headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace").strip()
