"""The Runtime's entry point. Do not change it: write the agent in agent.py as run(prompt) -> (answer, tools_used)."""
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp

import agent

app = BedrockAgentCoreApp()
NAME = os.environ.get("AGENT_NAME", "agent")      # the hub sets it from the application's name


@app.entrypoint
def invoke(payload, context=None):
    answer, tools_used = agent.run(str(payload.get("prompt", "")))
    return {"agent": NAME, "answer": answer, "tools_used": tools_used}


if __name__ == "__main__":
    app.run()
