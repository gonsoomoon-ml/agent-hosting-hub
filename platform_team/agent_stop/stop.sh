#!/usr/bin/env bash
# Stop one hosted agent: block its entry on the agent gateway, then end its sessions (the recent ones, or those given).
#   platform_team/agent_stop/stop.sh <agent> [--session <ID> ...]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ $# -ge 1 ] || { echo "usage: stop.sh <agent> [--session <ID> ...]" >&2; exit 2; }
# The hub's prefix, region and model: the three hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
cd "$repo"
exec uv run python -m platform_team.agent_stop.stop_agent stop "$@"
