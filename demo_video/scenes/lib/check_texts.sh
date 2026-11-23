#!/usr/bin/env bash
# The text check of a take: every screen kept in <take>.texts.txt (one per shot, and every screen a Claude Code session
# showed) is searched for a 12-digit number (an account ID), an e-mail address and the shape of an AWS access key ID
# (AKIA, a long-term key, or ASIA, a temporary one, and 16 capitals or digits). The developer PC's own name dev@dev-pc
# is not an address: it is masked, not dropped, so the rest of its line is still searched.
#   demo_video/scenes/lib/check_texts.sh <take>.texts.txt
# Prints each line found and exits 1; else one line and exit 0. A screen's text is chosen by programs in the container,
# so a printed line has its control characters dropped first (tab and newline kept; the 8-bit ones too), then every
# 12-digit number and key ID in it masked, then it is cut after 300 characters.
set -euo pipefail
[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: demo_video/scenes/lib/check_texts.sh <take>.texts.txt"; exit 2; }
found="$(sed 's/dev@dev-pc/<developer PC>/g' "$1" |
  grep -nP '(?<![0-9])[0-9]{12}(?![0-9])|[\w.+-]+@[\w-]+\.[A-Za-z]{2,}|(AKIA|ASIA)[A-Z0-9]{16}' || true)"
if [ -n "$found" ]; then
  echo "the screen's text holds a 12-digit number, an e-mail address or an access key ID:"
  # the controls go before the masks (a control character between digits would hide a number from them); every
  # 12-digit number masked, also two joined by one character (a sed pattern that eats the neighbour misses one)
  printf '%s\n' "$found" | perl -ne 'my $u = utf8::decode($_);
    s/[\x00-\x08\x0b-\x1f\x7f-\x9f]//g;
    s/(?<![0-9])[0-9]{12}(?![0-9])/<12 digits>/g;
    s/(?:AKIA|ASIA)[A-Z0-9]{16}/<access key ID>/g;
    s/^(.{300}).+/$1 [cut]/;
    utf8::encode($_) if $u; print'
  exit 1
fi
echo "texts: no 12-digit number, no e-mail address and no access key ID in $(grep -c '^== ' "$1") screens"
