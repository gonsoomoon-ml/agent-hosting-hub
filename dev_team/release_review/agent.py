"""release_review: checks a change description against the release rules and files a review request when one is broken."""
import os

import boto3

import graph
import hub_tools

_client = None
_graph = None


def ask_model(system: str, user: str) -> str:
    """One Bedrock Converse call in HUB_REGION with MODEL_ID (an inference profile ID). The client is made on first use."""
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=os.environ["HUB_REGION"])
    resp = _client.converse(
        modelId=os.environ["MODEL_ID"],
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": 300, "temperature": 0},
    )
    return "".join(part.get("text", "") for part in resp["output"]["message"]["content"])


def run(prompt: str) -> tuple[str, list]:
    global _graph
    if _graph is None:
        _graph = graph.build(call_tool=hub_tools.call_tool, ask_model=ask_model)
    out = _graph.invoke({"prompt": prompt})
    return out["answer"], out["tools_used"]
