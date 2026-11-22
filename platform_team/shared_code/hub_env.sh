# Sourced by publish.sh, reject.sh, rollout.sh and guardrail.sh, with $repo set to the repo root. The rule for .env (README, ".env"), as make
# and e2e_hosting.py follow it (platform_team/shared_code/config.py, env_file_updates):
# - only the lines AWS_REGION=..., DEMO_PREFIX=... and MODEL_ID=... are read, and they win over the shell;
#   a line with no value (DEMO_PREFIX=) is the same as no line;
#   nothing else in the file is read or exported (credentials there never replace the caller's);
# - when HUB_ENV_LOADED is set (make, or e2e_hosting.py, read .env already), .env is not read again.
if [ -z "${HUB_ENV_LOADED:-}" ] && [ -f "$repo/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      AWS_REGION=?* | DEMO_PREFIX=?* | MODEL_ID=?*) export "$line" ;;
    esac
  done <"$repo/.env"
fi
export HUB_ENV_LOADED=1
