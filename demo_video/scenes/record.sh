#!/usr/bin/env bash
# Record one take of the demo video with the video plugin's record_demo.mjs.
#   demo_video/scenes/record.sh <take> [max seconds] [--lang ko]
# <take> is a folder of demo_video/scenes/ with a storyboard.mjs. The storyboard names the surfaces it films in one
# line, `export const surfaces = ['hub', 'dev', 'user'];` (the hub screen on 127.0.0.1:8300, the developer PC's
# terminal on 127.0.0.1:7681, the user's shell on 127.0.0.1:7682); each must answer before anything is recorded.
# The take goes to demo_video/out/raw/<take>.webm with its camlog (<take>.camlog.json) and the text of the screen at
# each shot and of every screen a Claude Code session showed (<take>.texts.txt); a take recorded before is moved to
# demo_video/out/raw/old/ first. Then this prints the shots, the notes and any shot whose selector matched nothing,
# and looks for a 12-digit number or an e-mail address in the texts (lib/check_texts.sh). Exit 0 when the storyboard ended well, nothing was missing and nothing was found; else 1.
# Needs DEMO_VIDEO_PLUGIN (the plugin's scripts folder) and PLAYWRIGHT_ROOT (a folder with node_modules/playwright).
set -euo pipefail

USAGE="usage: demo_video/scenes/record.sh <take> [max seconds] [--lang ko]"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
take="" max="" lang=ko
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) [ $# -ge 2 ] || { echo "$USAGE"; exit 2; }; lang="$2"; shift 2 ;;
    *) if [ -z "$take" ]; then take="$1"; elif [ -z "$max" ] && [[ "$1" =~ ^[0-9]+$ ]]; then max="$1"; else
         echo "$USAGE"; exit 2; fi; shift ;;
  esac
done
max="${max:-150}"
[ -n "$take" ] || { echo "$USAGE"; exit 2; }
[[ "$take" =~ ^[0-9]{2}-[a-z][a-z-]*$ ]] && [ -f "$here/$take/storyboard.mjs" ] ||
  { echo "no take '$take' (a folder of demo_video/scenes/ with a storyboard.mjs)"; exit 2; }
[[ "$lang" =~ ^[a-z]{2}$ ]] || { echo "$USAGE"; exit 2; }
plugin="${DEMO_VIDEO_PLUGIN:-}"
[ -n "$plugin" ] && [ -f "$plugin/record_demo.mjs" ] || {
  echo "DEMO_VIDEO_PLUGIN must name the scripts folder of the demo-video plugin (record_demo.mjs, term.mjs):" \
       "https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video"; exit 2; }
[ -n "${PLAYWRIGHT_ROOT:-}" ] && [ -d "$PLAYWRIGHT_ROOT/node_modules/playwright" ] || {
  echo "PLAYWRIGHT_ROOT must name a folder with node_modules/playwright"; exit 2; }

# the surfaces the storyboard films, each up
declare -A url=([hub]=http://127.0.0.1:8300 [dev]=http://127.0.0.1:7681 [user]=http://127.0.0.1:7682)
declare -A start=([hub]="make ui" [dev]="demo_video/tools/dev_pc/run.sh term" [user]="demo_video/tools/user_shell.sh up")
line="$(grep -E "^export const surfaces = \[[^]]*\];$" "$here/$take/storyboard.mjs" || true)"
read -r -a surfaces <<<"$(printf '%s' "$line" | sed -E "s/^[^[]*\[//; s/\].*$//; s/[',]/ /g")"
[ ${#surfaces[@]} -gt 0 ] || { echo "$take/storyboard.mjs names no surface (export const surfaces = [...];)"; exit 2; }
for s in "${surfaces[@]}"; do
  [ -n "${url[$s]:-}" ] || { echo "$take/storyboard.mjs names an unknown surface '$s' (hub, dev, user)"; exit 2; }
  curl -fsS -m 5 -o /dev/null "${url[$s]}/" 2>/dev/null ||
    { echo "the surface '$s' does not answer on ${url[$s]}: start it with ${start[$s]}"; exit 1; }
done

raw="$repo/demo_video/out/raw"
mkdir -p "$raw"
if [ -e "$raw/$take.webm" ]; then
  mkdir -p "$raw/old"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  for f in "$raw/$take".webm "$raw/$take".camlog.json "$raw/$take".texts.txt "$raw/$take".error.png; do
    [ -e "$f" ] && mv "$f" "$raw/old/$(basename "$f" | sed "s/^$take/$take-$stamp/")"
  done
  echo "the take recorded before is in demo_video/out/raw/old/ ($take-$stamp.*)"
fi

status=0
node "$plugin/record_demo.mjs" --url "${url[${surfaces[0]}]}" --storyboard "$here/$take/storyboard.mjs" --name "$take" \
  --out "$raw" --max-seconds "$max" --playwright-root "$PLAYWRIGHT_ROOT" --lang "$lang" || status=$?

camlog="$raw/$take.camlog.json"
[ -f "$camlog" ] || { echo "no camlog: the recorder did not finish"; exit 1; }
echo "== $take: $(jq -r '"\(.duration_s | floor) s, ok \(.ok), page errors \(.errors | length)"' "$camlog")"
jq -r '.log[] | if .kind == "shot" then "\(.t)\tshot \(.key)\(if .label then "\t" + .label else "" end)\(if .missing then "\tMISSING: the selector matched nothing" else "" end)"
               else "\(.t)\t\(.kind)\(if .message then "\t" + .message else "" end)" end' "$camlog"
missing="$(jq -r '[.log[] | select(.missing) | .key] | join(" ")' "$camlog")"
[ -z "$missing" ] || { echo "missing: $missing"; status=1; }
texts="$raw/$take.texts.txt"
[ ! -f "$texts" ] || "$here/lib/check_texts.sh" "$texts" || status=1
[ "$(jq -r .ok "$camlog")" = true ] || status=1
exit "$status"
