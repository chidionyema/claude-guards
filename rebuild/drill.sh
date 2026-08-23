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

[ "$FAIL" = 0 ] || { echo; echo "DRILL FAILED"; exit 1; }
echo; echo "DRILL PASSED"
