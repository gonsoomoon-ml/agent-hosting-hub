#!/usr/bin/env bash
# Turn a company policy on for every hosted agent (log-only or active), switch its mode, turn it off, or report what
# it matched in the last hour.
#   platform_team/company_policy/rollout.sh <policy> log-only|active|off|report
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ $# -eq 2 ] || { echo "usage: rollout.sh <policy> log-only|active|off|report" >&2; exit 2; }
# The hub's prefix, region and model: the three hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
cd "$repo"
exec uv run python -m platform_team.company_policy.policy_rollout "$@"
