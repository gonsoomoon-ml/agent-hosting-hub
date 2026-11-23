#!/usr/bin/env bash
# The user's shell of the demo video: a terminal in the browser where a person of a team asks the hosted agents.
#   demo_video/tools/user_shell.sh up      ttyd on 127.0.0.1:7682 (this PC only) with the user's bash
#   demo_video/tools/user_shell.sh down    stop it
# The bash runs on this PC with the credentials of the person who records: the hub has no user role of its own (a
# user is any IAM principal that may invoke the agent gateway). Its prompt is "사용자 $ ", it starts in the repo's root
# (so demo_scenes/inputs/... are found as the scenes type them), demo_scenes/ is last on its PATH (ask, search ...),
# and its environment holds the hub's Region and prefix. It reads no rc file and keeps no history. Anything on this
# PC that can reach 127.0.0.1:7682 gets that shell: start it for the recording only, and stop it after.
set -euo pipefail

usage() { echo "usage: demo_video/tools/user_shell.sh up | down"; exit 2; }
[ $# -eq 1 ] || usage
case "$1" in up | down) ;; *) usage ;; esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
# The hub's prefix and Region: the hub lines of <repo>/.env, as make reads them (README, ".env").
. "$repo/platform_team/shared_code/hub_env.sh"
region="${AWS_REGION:-us-west-2}"
prefix="${DEMO_PREFIX:-hub}"
out="$repo/demo_video/out/user-shell"
port=7682

stop() {
  if [ -f "$out/ttyd.pid" ]; then
    kill "$(<"$out/ttyd.pid")" 2>/dev/null || true
    rm -f "$out/ttyd.pid"
  fi
}

case "$1" in
  up)
    if [ -L "$out" ] || [ -L "$repo/demo_video/out" ]; then
      echo "demo_video/out or its user-shell folder is a symbolic link: not followed"
      exit 1
    fi
    if [ -f "$out/ttyd.pid" ] && kill -0 "$(<"$out/ttyd.pid")" 2>/dev/null; then
      echo "user shell: http://127.0.0.1:$port (already running)"
      exit 0
    fi
    AWS_REGION="$region" AWS_DEFAULT_REGION="$region" aws sts get-caller-identity >/dev/null 2>&1 ||
      { echo "the shell's AWS credentials do not answer in $region: the user's shell needs them"; exit 1; }
    mkdir -p "$out"
    # loopback only (-i lo), only pages ttyd serves may open the terminal (-O), every page a new bash
    nohup ttyd -i lo -p "$port" -O -w "$repo" \
      env PS1='사용자 $ ' PATH="$PATH:$repo/demo_scenes" HISTFILE= LANG=C.UTF-8 TERM=xterm-256color \
      AWS_REGION="$region" AWS_DEFAULT_REGION="$region" DEMO_PREFIX="$prefix" \
      bash --norc --noprofile -i >"$out/ttyd.log" 2>&1 &
    echo $! >"$out/ttyd.pid"
    for _ in $(seq 1 20); do
      curl -fsS -o /dev/null "http://127.0.0.1:$port/" 2>/dev/null && break
      sleep 0.5
    done
    curl -fsS -o /dev/null "http://127.0.0.1:$port/" 2>/dev/null || { stop; echo "ttyd did not start (see $out/ttyd.log)"; exit 1; }
    echo "user shell: http://127.0.0.1:$port (this PC only), prompt '사용자 \$', Region $region, prefix $prefix"
    ;;
  down)
    stop
    echo "stopped: the user's shell"
    ;;
esac
