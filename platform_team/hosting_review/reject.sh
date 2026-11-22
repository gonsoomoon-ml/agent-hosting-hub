#!/usr/bin/env bash
# Reject a submission that failed the hosting review, and remove what the review made for it.
#   platform_team/hosting_review/reject.sh <agent> "<reason>"
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ $# -eq 2 ] || { echo "usage: reject.sh <agent> \"<reason>\"" >&2; exit 2; }
# The hub's prefix, region and model: the three hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
cd "$repo"
exec uv run python -m platform_team.hosting_review.reject_agent "$@"
