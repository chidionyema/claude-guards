#!/usr/bin/env bash
# Take a machine with git, python3 and nothing else to a working estate.
#
# LAW 19: an exit that has never been drilled is a hope, not a portability
# story. This script IS the exit, and rebuild/drill.sh is what proves it still
# works, against a throwaway home, with no admin password and no second user
# account.
#
#   bootstrap.sh                 rebuild this machine
#   bootstrap.sh --into DIR      rebuild into a throwaway home. The drill.
#
# What it does NOT do is ask you for anything until the end. Everything a
# machine can do for itself happens first; what is left is the list of
# sign-ins, and that list is the score (LAW 27: once per identity, ever).
set -uo pipefail

REPO="${ESTATE_REPO:-https://github.com/chidionyema/claude-estate.git}"
TARGET="$HOME"
DRILL=0
[ "${1:-}" = "--into" ] && { TARGET="$2"; DRILL=1; }

say() { printf '\n=== %s\n' "$*"; }
STEPS=0

say "1/4  the configuration repository"
if [ -d "$TARGET/.claude/.git" ]; then
  echo "already cloned; fetching"
  git -C "$TARGET/.claude" fetch --quiet origin && \
  git -C "$TARGET/.claude" submodule update --init --recursive --quiet
else
  mkdir -p "$TARGET"
  git clone --recursive --quiet "$REPO" "$TARGET/.claude" || {
    echo "FAILED to clone $REPO"; exit 1; }
fi
echo "$(git -C "$TARGET/.claude" ls-files | wc -l | tr -d ' ') files, submodule at \
$(git -C "$TARGET/.claude/scripts" rev-parse --short HEAD 2>/dev/null || echo MISSING)"

say "2/4  the files that live outside it"
python3 "$TARGET/.claude/scripts/tracked.py" --restore \
  ${DRILL:+--into "$TARGET"} 2>&1 | grep -Ev '^$' | sed 's/^/    /'

say "3/4  the scheduled jobs, rendered for THIS home"
python3 "$TARGET/.claude/scripts/jobs/render.py" --write \
  --home "$TARGET" --into "$TARGET/Library/LaunchAgents" 2>&1 | sed 's/^/    /'
if [ "$DRILL" = "0" ]; then
  echo "    loading them:"
  for f in "$TARGET"/Library/LaunchAgents/*.plist; do
    l=$(basename "$f" .plist)
    launchctl bootout "gui/$(id -u)/$l" 2>/dev/null
    launchctl bootstrap "gui/$(id -u)" "$f" 2>/dev/null && echo "      up   $l" \
      || echo "      FAIL $l"
  done
else
  echo "    drill: rendered but not loaded, a throwaway home owns no LaunchAgents"
fi

say "4/4  what is left, and it is only sign-ins"
python3 - "$TARGET" <<'PY'
import os, re, sys
target = sys.argv[1]
doc = os.path.join(target, ".claude/scripts/rebuild/PREREQUISITES.md")
rows = []
for line in open(doc, encoding="utf-8"):
    m = re.match(r"\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
    if m and not m.group(1).startswith("path"):
        rows.append(m.groups())
missing = [r for r in rows
           if not os.path.exists(os.path.expanduser(r[0].replace("~", target, 1)))]
print(f"    {len(rows)} things this repository deliberately does not hold.")
print(f"    {len(missing)} of them are absent here:\n")
for path, what, how in missing:
    print(f"      {path}\n          {what}\n          -> {how}")
print(f"\n    THE SCORE: {len(missing)} manual steps.")
print("    LAW 27 allows the browser sign-ins. Everything else on that list is")
print("    a defect in this script, not a step.")
PY
