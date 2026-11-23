#!/usr/bin/env bash
# The hosted agents' use of the hub, from CloudWatch (reads only): per agent its calls, sessions, errors, CPU and
# memory, and per catalog tool its calls, over the last [minutes] minutes (60 if not given).
#   platform_team/agent_monitoring/usage.sh [minutes]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ $# -le 1 ] || { echo "usage: usage.sh [minutes]" >&2; exit 2; }
# The hub's prefix, region and model: the three hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
cd "$repo"
exec uv run python -m platform_team.agent_monitoring.usage_report "$@"
