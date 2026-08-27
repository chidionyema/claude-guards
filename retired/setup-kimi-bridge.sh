#!/usr/bin/env bash
# Kimi browser bridge, one command.
#
# The bridge runs in its own virtualenv on purpose. consultd.py runs under
# Apple's signed /usr/bin/python3 so macOS does not re-prompt for access on
# every launch, and that interpreter must not grow a Playwright dependency.
# The two talk over loopback HTTP instead, so neither can break the other.
set -euo pipefail

ROOT="${KIMI_BRIDGE_HOME:-$HOME/.kimi-bridge}"
VENV="$ROOT/venv"

# 3.14 has no Playwright wheel yet. Pick the newest interpreter that does.
PY=""
for c in python3.13 python3.12 python3.11; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
[ -n "$PY" ] || { echo "need python 3.11, 3.12 or 3.13 for playwright" >&2; exit 1; }
echo "interpreter: $PY ($("$PY" -V 2>&1))"

mkdir -p "$ROOT/profile" "$ROOT/logs"
chmod 700 "$ROOT"

[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet playwright
"$VENV/bin/python" -m playwright install chromium

echo
echo "installed. next:"
echo "  $VENV/bin/python $HOME/.claude/scripts/kimi_bridge.py --login    # once, to sign in"
echo "  $VENV/bin/python $HOME/.claude/scripts/kimi_bridge.py --daemon"
echo "  $VENV/bin/python $HOME/.claude/scripts/kimi_bridge.py --health"
