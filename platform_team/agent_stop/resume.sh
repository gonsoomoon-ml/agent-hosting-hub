#!/usr/bin/env bash
# Resume a stopped agent: remove its stop policy, and nothing else.
#   platform_team/agent_stop/resume.sh <agent>
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ $# -eq 1 ] || { echo "usage: resume.sh <agent>" >&2; exit 2; }
# The hub's prefix, region and model: the three hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
cd "$repo"
exec uv run python -m platform_team.agent_stop.stop_agent resume "$@"
