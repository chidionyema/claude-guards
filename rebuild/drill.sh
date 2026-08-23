#!/usr/bin/env bash
# Prove the exit still works. LAW 19: a rebuild that has never been drilled is
# a hope, and one drilled once is a hope with a date on it.
#
# Rebuilds the whole estate from the remote into a throwaway home, then asserts
# the things that were actually wrong the first time it ran. No admin password,
# no second user account, nothing touched outside the temporary directory.
#
# Exit 0 with the score, or exit 1 naming the assertion that failed.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
D="$(mktemp -d "${TMPDIR:-/tmp}/estate-drill-XXXXXX")"
trap 'rm -rf "$D"' EXIT
FAIL=0

check() {  # check <description> <expected> <actual>
  if [ "$2" = "$3" ]; then printf '  ok    %s (%s)\n' "$1" "$3"
  else printf '  FAIL  %s: expected %s, got %s\n' "$1" "$2" "$3"; FAIL=1; fi
}

OUT="$(bash "$HERE/bootstrap.sh" --into "$D" 2>&1)" || {
  echo "$OUT" | tail -20; echo "bootstrap failed"; exit 1; }

echo "assertions:"
check "no plist carries another machine's home" 0 \
      "$(grep -rl "$HOME" "$D/Library/LaunchAgents" 2>/dev/null | wc -l | tr -d ' ')"
check "every declared job rendered for this home" \
      "$(python3 -c 'import json;print(len(json.load(open("'"$HERE"'/../jobs/jobs.json"))))')" \
      "$(grep -rl "$D" "$D/Library/LaunchAgents" 2>/dev/null | wc -l | tr -d ' ')"
check "the laws symlink resolves" "# The laws" "$(head -1 "$D/.claude/AGENTS.md" 2>/dev/null)"
check "the guards came with the clone" yes \
      "$([ -x "$D/.claude/scripts/tracked.py" ] && echo yes || echo no)"
check "the commit gate came with the clone" yes \
      "$([ -x "$D/.claude/scripts/hooks/pre-commit" ] && echo yes || echo no)"
check "no credential was restored" 0 \
      "$(ls "$D/.config"/*/secrets.sh "$D/.claude/.credentials.json" 2>/dev/null | wc -l | tr -d ' ')"

SCORE="$(echo "$OUT" | sed -n 's/.*THE SCORE: \([0-9]*\) manual steps.*/\1/p')"
echo
echo "  files rebuilt: $(find "$D" -type f -not -path '*/.git/*' | wc -l | tr -d ' ')"
echo "  THE SCORE:     ${SCORE:-unknown} manual steps"
echo "  the target is the sign-ins only. Anything above that is the backlog."

# LAW 28: an instrument nobody reads is not an instrument. The board is handed
# to every session at startup, so this reaches a reader without a new channel.
board() {
  python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import tracked; tracked.board(sys.argv[2], sys.argv[3], "rebuild-drill")' \
    "$HERE/.." "$1" "$2" 2>/dev/null || true
}

if [ "$FAIL" != 0 ]; then
  echo; echo "DRILL FAILED"
  board drill-failed "The rebuild drill failed. The estate cannot currently be rebuilt from its own repositories. Run scripts/rebuild/drill.sh to see which assertion broke. LAW 19: the exit is the leverage, and it is down."
  exit 1
fi
echo; echo "DRILL PASSED"
board drill-passed "Rebuild drill passed: the estate rebuilt from its remotes into a throwaway home, ${SCORE:-?} manual steps remaining. PASS, not NOT-RUN."
