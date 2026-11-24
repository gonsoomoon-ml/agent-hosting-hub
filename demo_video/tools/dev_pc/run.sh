#!/usr/bin/env bash
# The developer PC of the demo video: a container (image hub-dev-pc) with Claude Code on Amazon Bedrock and the hub's
# developer role. Run it from anywhere, as the person who records, with that person's AWS credentials: they make the
# two temporary credentials below and read the catalog's ID, and they never enter the container.
#   demo_video/tools/dev_pc/run.sh build          the image (no build context: no file of this PC goes into it)
#   demo_video/tools/dev_pc/run.sh creds          the two temporary credentials (again before a take: replaced in place)
#   demo_video/tools/dev_pc/run.sh up             the container, with a fresh checkout in /home/dev/work
#   demo_video/tools/dev_pc/run.sh check          Claude Code answers through Bedrock; the route; the MCP tools; search;
#                                                 who the tools are
#   demo_video/tools/dev_pc/run.sh term           ttyd on 127.0.0.1:7681 into the container
#   demo_video/tools/dev_pc/run.sh agent <name>   put the repo's agent into dev_team/ (what was there is kept aside)
#   demo_video/tools/dev_pc/run.sh stop           stop ttyd and the container (the home stays)
#   demo_video/tools/dev_pc/run.sh forget         delete the two credential files
#   demo_video/tools/dev_pc/run.sh down           stop, then forget
# The two credentials go into the container, and nothing else (the folder demo_video/out/dev-pc/creds, read-only at
# /run/dev-pc):
#   developer.ini  the developer role's session (sts:AssumeRole, session name developer, one hour): the container's
#                  default AWS profile, so the shell, the scene commands, the MCP proxy and every tool Claude Code
#                  starts run as the developer
#   bedrock.json   a federation token (sts:GetFederationToken, name hub-video-claude, four hours) whose session policy
#                  (bedrock-policy.json.tmpl) allows only invoking the video's two Claude models: Claude Code reads it
#                  for its own model calls through the settings key awsCredentialExport
# No credential value is printed or logged: creds prints the two principals (the account masked) and their expiry.
# The container can write one folder of this PC: its home, demo_video/out/dev-pc/home (/home/dev). So once that folder
# exists, run.sh makes, changes and deletes things inside it only through docker exec as the user dev, where a link
# planted in it resolves inside the container; no command of this PC runs on a path under it.
set -euo pipefail

USAGE="usage: demo_video/tools/dev_pc/run.sh build | creds | up | check | term | agent <name> | stop | forget | down"
usage() { echo "$USAGE"; exit 2; }
[ $# -ge 1 ] || usage
case "$1" in
  build | creds | up | check | term | stop | forget | down) [ $# -eq 1 ] || usage ;;
  agent) [ $# -eq 2 ] || usage ;;
  *) usage ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
# The hub's prefix and Region: the hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
region="${AWS_REGION:-us-west-2}"
prefix="${DEMO_PREFIX:-hub}"
out="$repo/demo_video/out/dev-pc"
creds="$out/creds"
home="$out/home"
image=hub-dev-pc
name=hub-dev-pc

# Every 12-digit number (an account ID) masked.
mask() { sed -E 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<ACCOUNT>\2/g; s/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<ACCOUNT>\2/g'; }

# What a program in the container printed, as this PC's terminal shows it: its control characters dropped (tab and
# newline kept; the 8-bit ones too), then every 12-digit number masked as mask does (after the controls, which could
# split a number), then each line cut after 300 characters.
shown() {
  perl -ne 'my $u = utf8::decode($_);
    s/[\x00-\x08\x0b-\x1f\x7f-\x9f]//g;
    s/(?<![0-9])[0-9]{12}(?![0-9])/<ACCOUNT>/g;
    s/^(.{300}).+/$1 [cut]/;
    utf8::encode($_) if $u; print'
}

# An AWS call in the hub's Region; its error, if any, is printed with the account masked.
aws_hub() {
  local err status=0
  err="$(mktemp)"
  AWS_REGION="$region" AWS_DEFAULT_REGION="$region" aws --region "$region" "$@" 2>"$err" || status=$?
  [ "$status" -eq 0 ] || mask <"$err" >&2
  rm -f "$err"
  return "$status"
}

# The folders run.sh writes on this PC: refused when one of them is a symbolic link.
refuse_links() {
  local p
  for p in "$out" "$home" "$creds"; do
    if [ -L "$p" ]; then
      echo "${p#"$repo"/} is a symbolic link: run.sh does not follow it"
      exit 1
    fi
  done
}

running() { docker exec "$name" true >/dev/null 2>&1; }

# A command in the container's working folder, as the user dev.
box() { docker exec -w /home/dev/work "$@"; }

# The blackhole route for the instance metadata service is in place (read as dev; ip route show needs no right).
route_ok() { docker exec "$name" /usr/bin/ip route show 169.254.169.254 2>/dev/null | grep -q '^blackhole 169\.254\.169\.254'; }

need_route() {
  route_ok || { echo "the container has no blackhole route for the instance metadata service: run.sh up again"; exit 1; }
}

do_stop() {
  if [ -f "$out/ttyd.pid" ]; then
    kill "$(<"$out/ttyd.pid")" 2>/dev/null || true
    rm -f "$out/ttyd.pid"
  fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  echo "stopped: ttyd and the container (the home demo_video/out/dev-pc/home stays)"
}

do_forget() {
  rm -f "$creds/developer.ini" "$creds/bedrock.json" "$creds"/.sts.* "$creds"/.*.new
  echo "deleted: the two credential files"
}

case "$1" in
  build)
    docker build -t "$image" --build-arg "DEV_UID=$(id -u)" - <"$here/Dockerfile"
    ;;

  creds)
    refuse_links
    git -C "$repo" check-ignore -q demo_video/out/dev-pc/creds/developer.ini ||
      { echo "demo_video/out/ is not git-ignored: no credential file is written"; exit 1; }
    umask 077
    mkdir -p "$creds"
    chmod 700 "$out" "$creds"
    account="$(aws_hub sts get-caller-identity --query Account --output text)"
    role="$(aws_hub ssm get-parameter --name "/$prefix/platform/dev_role_arn" --query Parameter.Value --output text)"
    tmp="$(mktemp "$creds/.sts.XXXXXX")"
    trap 'rm -f "$tmp" "$creds"/.*.new' EXIT
    # the developer role: the container's default profile
    aws_hub sts assume-role --role-arn "$role" --role-session-name developer --duration-seconds 3600 --output json >"$tmp"
    jq -r '.Credentials | "[default]\naws_access_key_id = \(.AccessKeyId)\naws_secret_access_key = \(.SecretAccessKey)\naws_session_token = \(.SessionToken)"' \
      "$tmp" >"$creds/.developer.ini.new"
    mv -f "$creds/.developer.ini.new" "$creds/developer.ini"
    jq -r '"developer role:          \(.AssumedRoleUser.Arn)  expires \(.Credentials.Expiration)"' "$tmp" | mask
    # Claude Code's own model calls: the two models and nothing else
    policy="$(sed -e "s/<ACCOUNT>/$account/g" -e "s/<REGION>/$region/g" "$here/bedrock-policy.json.tmpl")"
    aws_hub sts get-federation-token --name hub-video-claude --duration-seconds 14400 --policy "$policy" --output json >"$tmp"
    jq '{Credentials: (.Credentials | {AccessKeyId, SecretAccessKey, SessionToken, Expiration})}' "$tmp" >"$creds/.bedrock.json.new"
    mv -f "$creds/.bedrock.json.new" "$creds/bedrock.json"
    jq -r '"Claude Code on Bedrock:  \(.FederatedUser.Arn)  expires \(.Credentials.Expiration)"' "$tmp" | mask
    ;;

  up)
    refuse_links
    docker image inspect "$image" >/dev/null 2>&1 || { echo "no image $image: run.sh build first"; exit 1; }
    [ -f "$creds/developer.ini" ] && [ -f "$creds/bedrock.json" ] || { echo "no credentials: run.sh creds first"; exit 1; }
    registry="$(aws_hub ssm get-parameter --name "/$prefix/platform/registry_id" --query Parameter.Value --output text)"
    [[ "$registry" =~ ^[A-Za-z0-9-]+$ ]] || { echo "no catalog ID under /$prefix/platform: is the hub deployed?"; exit 1; }
    docker rm -f "$name" >/dev/null 2>&1 || true
    mkdir -p "$home"
    chmod 700 "$out" "$home"
    # No port is published, and no process gains a privilege (no-new-privileges). The instance metadata service of
    # this PC is out of reach: the SDKs do not ask it, and its address is a blackhole route in the container's network,
    # set once by root (by absolute path, with a fixed PATH); the user dev holds no capability to remove it. Without
    # the route the container is removed.
    docker run -d --name "$name" --hostname dev-pc --init --user dev --workdir /home/dev --cap-add NET_ADMIN \
      --security-opt no-new-privileges --volume "$home:/home/dev" --volume "$creds:/run/dev-pc:ro" \
      --env AWS_SHARED_CREDENTIALS_FILE=/run/dev-pc/developer.ini --env AWS_EC2_METADATA_DISABLED=true \
      --env AWS_REGION="$region" --env AWS_DEFAULT_REGION="$region" --env DEMO_PREFIX="$prefix" \
      "$image" >/dev/null

    if ! docker exec --user root --env PATH=/usr/sbin:/usr/bin:/sbin:/bin "$name" /usr/bin/ip route add blackhole 169.254.169.254/32 ||
      ! route_ok; then
      docker rm -f "$name" >/dev/null 2>&1 || true
      echo "the blackhole route for the instance metadata service could not be set: the container is removed"
      exit 1
    fi
    # A fresh checkout, all of it written inside the container: the working folder emptied (the Python environment
    # .venv is kept), then the repo's tracked files of these folders (no state, no build, no .env) from this PC's
    # standard input. In the story the developer makes quality_agent, so it is left out (run.sh agent puts it in).
    docker exec -u dev "$name" sh -c 'cd /home/dev && rm -rf prepared && { [ ! -L work ] || rm -f work; } &&
      mkdir -p work && find work -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +'
    git -C "$repo" ls-files -z -- dev_team platform_team demo_scenes pyproject.toml uv.lock |
      grep -z -v '^dev_team/quality_agent/' | (cd "$repo" && tar --null -T - -cf -) |
      docker exec -i -u dev "$name" tar -x -C /home/dev/work
    docker exec -i -u dev "$name" sh -c 'mkdir -p /home/dev/work/.claude && cat > /home/dev/work/.claude/settings.json' \
      <"$here/settings.json"
    docker exec -i -u dev "$name" sh -c 'cat > /home/dev/work/CLAUDE.md' <"$here/CLAUDE.md"
    sed -e "s/<REGION>/$region/g" -e "s/<REGISTRY_ID>/$registry/g" "$here/mcp.json.tmpl" |
      docker exec -i -u dev "$name" sh -c 'cat > /home/dev/work/.mcp.json'
    # once, so that the first command of a take prints only its own lines
    docker exec -u dev -w /home/dev/work "$name" uv sync --quiet
    agents="$(docker exec -u dev "$name" ls /home/dev/work/dev_team | tr '\n' ' ' | shown)"
    echo "up: $name, the checkout in /home/dev/work (dev_team: $agents), quality_agent comes with run.sh agent quality_agent"
    ;;

  check)
    running || { echo "the container is not running: run.sh up first"; exit 1; }
    need_route
    failed=0
    echo "== claude --version"
    box "$name" claude --version 2>&1 | shown
    echo "== claude -p: Claude Code answers through Amazon Bedrock"
    t0=$SECONDS
    box "$name" claude -p "Answer with the single word: ready" 2>&1 | shown || failed=1
    echo "($((SECONDS - t0)) s)"
    echo "== this PC's instance metadata service is out of reach"
    if box "$name" curl -s -m 3 -o /dev/null -X PUT http://169.254.169.254/latest/api/token \
         -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>&1 | shown; then
      echo "it answered"
      failed=1
    else
      echo "no answer"
    fi
    echo "== the user dev holds no capability and cannot delete the route"
    cap="$(box "$name" grep CapEff /proc/self/status 2>&1 | shown)" || true
    if [[ "$cap" =~ ^CapEff:[[:space:]]+0+$ ]]; then
      echo "$cap (the user dev holds no effective capability)"
    else
      echo "$cap (not zero: the user dev holds a capability)"
      failed=1
    fi
    if del="$(docker exec "$name" /usr/bin/ip route del blackhole 169.254.169.254/32 2>&1)"; then
      docker rm -f "$name" >/dev/null 2>&1 || true
      echo "the user dev deleted the route: the container is removed"
      exit 1
    fi
    echo "the user dev cannot delete the route: $(printf '%s' "$del" | shown)"
    echo "== the tools of the MCP server hub-catalog (.mcp.json)"
    box -i "$name" /opt/uv/tools/mcp-proxy-for-aws/bin/python - <<'PY' 2>&1 | shown || failed=1
import asyncio, json, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server = json.load(open(".mcp.json"))["mcpServers"]["hub-catalog"]

async def main():
    params = StdioServerParameters(command=server["command"], args=server["args"], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                print(tool.name)

asyncio.run(main())
PY
    echo '== search "part specification tool" (the developer role)'
    box "$name" search "part specification tool" 2>&1 | shown || failed=1
    echo "== aws sts get-caller-identity in the container's shell"
    box "$name" aws sts get-caller-identity --query Arn --output text 2>&1 | shown || failed=1
    echo "== aws sts get-caller-identity through Claude Code's shell tool"
    cmd="aws sts get-caller-identity --query Arn --output text"
    seen="$(box "$name" claude -p "Run this shell command and show its output: $cmd" \
      --allowedTools "Bash($cmd)" --output-format stream-json --verbose 2> >(shown >&2) |
      jq -r 'select(.type == "user") | .message.content[]? | select(.type == "tool_result")
             | .content | if type == "array" then map(.text // "") | join("") else . end' | shown)" || failed=1
    echo "$seen"
    if [[ "$seen" == *":assumed-role/$prefix-dev-role/developer"* ]]; then
      echo "Claude Code's tools run as the developer role, not as Claude Code's Bedrock token"
    else
      echo "Claude Code's tools do not run as the developer role"
      failed=1
    fi
    [ "$failed" -eq 0 ] && echo "check: all passed" || { echo "check: something failed (see above)"; exit 1; }
    ;;

  term)
    refuse_links
    running || { echo "the container is not running: run.sh up first"; exit 1; }
    need_route
    if [ -f "$out/ttyd.pid" ] && kill -0 "$(<"$out/ttyd.pid")" 2>/dev/null; then
      echo "ttyd is running: http://127.0.0.1:7681"
      exit 0
    fi
    # loopback only (-i lo), and only pages served by ttyd itself may open the terminal (-O)
    nohup ttyd -i lo -p 7681 -O docker exec -it -w /home/dev/work -e TERM=xterm-256color "$name" bash >"$out/ttyd.log" 2>&1 &
    echo $! >"$out/ttyd.pid"
    for _ in $(seq 1 20); do
      curl -fsS -o /dev/null http://127.0.0.1:7681/ 2>/dev/null && break
      sleep 0.5
    done
    echo "ttyd: http://127.0.0.1:7681 (this PC only)"
    ;;

  agent)
    agent="$2"
    [[ "$agent" =~ ^[a-z][a-z0-9]*(_[a-z0-9]+)*$ ]] || { echo "agent name '$agent': not an agent name"; exit 2; }
    [ -n "$(git -C "$repo" ls-files -- "dev_team/$agent/agent.json")" ] ||
      { echo "no agent '$agent' in the repo's dev_team/"; exit 2; }
    refuse_links
    running || { echo "the container is not running: run.sh up first"; exit 1; }
    # Inside the container, as dev: what is in dev_team/<agent> (Claude Code's) moves to /home/dev/made-by-claude;
    # then the repo's tracked dev_team/<agent> comes in from this PC's standard input.
    kept="$agent-$(date +%Y%m%d-%H%M%S)"
    docker exec -u dev "$name" sh -c 'd="/home/dev/work/dev_team/$1"; if [ -e "$d" ] || [ -L "$d" ]; then
      mkdir -p /home/dev/made-by-claude && mv "$d" "/home/dev/made-by-claude/$2" &&
      echo "what was in dev_team/$1 is kept in /home/dev/made-by-claude/$2"; fi' sh "$agent" "$kept"
    git -C "$repo" ls-files -z -- "dev_team/$agent" | (cd "$repo" && tar --null -T - -cf -) |
      docker exec -i -u dev "$name" tar -x -C /home/dev/work
    echo "dev_team/$agent is now the repo's $agent"
    ;;

  stop)
    refuse_links
    do_stop
    ;;
  forget)
    refuse_links
    do_forget
    ;;
  down)
    refuse_links
    do_stop
    do_forget
    ;;
esac
