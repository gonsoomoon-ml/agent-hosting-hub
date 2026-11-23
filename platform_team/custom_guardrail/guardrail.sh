#!/usr/bin/env bash
# Attach the custom guardrail (the interceptor Lambda) to the agent gateway, detach it, or show where it stands.
#   platform_team/custom_guardrail/guardrail.sh attach|detach|status
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ $# -eq 1 ] || { echo "usage: guardrail.sh attach|detach|status" >&2; exit 2; }
# The hub's prefix, region and model: the three hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
cd "$repo"
exec uv run python -m platform_team.custom_guardrail.guardrail_attach "$@"
