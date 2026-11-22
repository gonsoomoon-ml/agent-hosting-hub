#!/usr/bin/env bash
# Publish an agent to the hub: upload its code, write its application to the catalog, ask for approval.
#   dev_team/agent_template/publish.sh <agent_dir> [variant]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ $# -ge 1 ] || { echo "usage: publish.sh <agent_dir> [variant]" >&2; exit 2; }
dir="$(cd "$1" && pwd)"
shift
# The hub's prefix, region and model: the three hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
cd "$repo"
exec uv run python -m platform_team.agent_catalog.publish_agent "$dir" "$@"
