#!/usr/bin/env bash
# The text check of a take: every screen kept in <take>.texts.txt (one per shot, and every screen a Claude Code session
# showed) is searched for a 12-digit number (an account ID) and an e-mail address. The developer PC's own name
# dev@dev-pc is not an address: it is masked, not dropped, so the rest of its line is still searched.
#   demo_video/scenes/lib/check_texts.sh <take>.texts.txt
# Prints each line found (a 12-digit number masked) and exits 1; else one line and exit 0.
set -euo pipefail
[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: demo_video/scenes/lib/check_texts.sh <take>.texts.txt"; exit 2; }
found="$(sed 's/dev@dev-pc/<developer PC>/g' "$1" |
  grep -nP '(?<![0-9])[0-9]{12}(?![0-9])|[\w.+-]+@[\w-]+\.[A-Za-z]{2,}' || true)"
if [ -n "$found" ]; then
  echo "the screen's text holds a 12-digit number or an e-mail address:"
  printf '%s\n' "$found" | sed -E 's/(^|[^0-9])[0-9]{12}([^0-9]|$)/\1<12 digits>\2/g'
  exit 1
fi
echo "texts: no 12-digit number and no e-mail address in $(grep -c '^== ' "$1") screens"
