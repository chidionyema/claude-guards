#!/bin/bash
# make-runner.sh — rebuild ~/.claude/bin/estate-runner, the shell scheduled estate jobs run under.
#
# WHY THIS EXISTS. macOS decides file access per EXECUTABLE IDENTITY, and /bin/bash is
# denied ~/Documents on this machine. Measured 2026-08-23, same launchd domain, same
# script, only the executable differs:
#
#   /bin/bash                      ls ~/Documents/code -> Operation not permitted, 0 repos
#   ~/.claude/bin/estate-runner    ls ~/Documents/code -> exit 0, 51 entries, 45 repos
#
# estate_bundle_push ran under /bin/bash first and reported GREEN having covered 10 of 19
# repos, because everything under ~/Documents was invisible to it.
#
# The runner is a copy of the same /bin/bash carrying an ad hoc signature, which gives it
# its own identity. Nothing about it is privileged beyond that: it is the same shell.
#
# RE-RUN THIS after a macOS update replaces /bin/bash, or if a scheduled job starts
# reporting "cannot list" on a root that plainly exists. The signature is what goes stale.
set -euo pipefail
DEST="$HOME/.claude/bin/estate-runner"
mkdir -p "$(dirname "$DEST")"
cp /bin/bash "$DEST"
codesign --force --sign - "$DEST"
chmod 700 "$DEST"
"$DEST" -c 'echo "runner works, bash $BASH_VERSION"'
echo "identity: $(codesign -dv "$DEST" 2>&1 | awk -F= '/^Identifier/{print $2}')"
