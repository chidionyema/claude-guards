#!/bin/bash
# Get everything out of the iCloud container that exists nowhere else, so the
# founder can turn iCloud Drive off with "Keep a Copy" and lose nothing.
# Renaming out of the container does not work (fileproviderd intercepts it).
# Copying does: it reads through the provider and writes to a plain path.
set -u
SRC="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
DST="$HOME/dev/icloud-rescue"
LOG="$HOME/.claude/state/icloud-rescue.log"
mkdir -p "$DST"
exec >>"$LOG" 2>&1
echo "=== rescue started $(date '+%F %T') ==="

# 1. What is in the container that is NOT in the live tree. No recursive find.
ls -1 "$SRC" > /tmp/icloud-top.txt 2>/dev/null
echo "container top-level entries: $(wc -l < /tmp/icloud-top.txt)"

#: STOP BEFORE THE DISK DOES.
#: Every byte this copies is a byte iCloud downloads onto the local disk first,
#: and the container is bigger than the free space. Measured 2026-08-23:
#: haworks-platform alone is 37.1 GB of 241,539 files against 61 GB free. Copying
#: the list in one pass with no check between items is the same shape of mistake
#: that took free space from 6.3G to 0.42G earlier the same evening and made
#: every scheduled job on the machine report a failure that never happened.
#:
#: So the floor is checked before each entry, not once at the start. Below it the
#: run stops and says what is left, which is a resumable state: entries already
#: copied are skipped by rsync next time.
FLOOR_GB="${ICLOUD_RESCUE_FLOOR_GB:-25}"
free_gb() { df -g /System/Volumes/Data | awk 'NR==2 {print $4+0}'; }

echo "floor: ${FLOOR_GB}G   free now: $(free_gb)G"
STOPPED=""
while IFS= read -r e; do
  [ -z "$e" ] && continue
  # the live locations the code tree actually lives in
  if [ -e "$HOME/dev/code/$e" ] || [ -e "$HOME/Documents/code/$e" ] || [ -e "$HOME/dev/$e" ]; then
    echo "SKIP-LOCAL  $e"
    continue
  fi
  #: Numeric compare. Shell compares as strings unless both sides are numbers,
  #: and "9" > "25" is true as a string, which would disarm this entirely.
  F=$(free_gb)
  if [ "$F" -lt "$FLOOR_GB" ]; then
    echo "STOP        free ${F}G is below the ${FLOOR_GB}G floor. Not starting $e."
    STOPPED="$e"
    break
  fi
  echo "RESCUE      $e   (free ${F}G)"
  rsync -a --exclude 'node_modules/' --exclude '.DS_Store' \
        "$SRC/$e" "$DST/" 2>&1 | tail -2
  echo "            after $e: free $(free_gb)G"
done < /tmp/icloud-top.txt

if [ -n "$STOPPED" ]; then
  echo "=== stopped at $STOPPED. Free space, then run this again; rsync resumes. ==="
fi

echo "=== copy finished $(date '+%F %T') ==="
du -sh "$DST" 2>/dev/null
echo "=== git-init anything with no history, so nothing is one delete from gone ==="
for d in "$DST"/*/; do
  [ -d "$d" ] || continue
  n=$(basename "$d")
  if [ ! -d "$d/.git" ]; then
    git -C "$d" init -q 2>/dev/null && \
    git -C "$d" add -A 2>/dev/null && \
    git -C "$d" -c user.email=chidionyema@gmail.com -c user.name=chidionyema \
        commit -q -m "rescued from the iCloud container, 2026-08-23

This tree existed only inside ~/Library/Mobile Documents and had no git history
at all. It is committed as found, before any edit, so the founder can turn
iCloud Drive off without this being the copy that disappears." 2>/dev/null && \
    echo "GIT-INIT    $n  ($(git -C "$d" ls-files | wc -l | tr -d ' ') files)"
  else
    echo "HAS-GIT     $n  branch=$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null) dirty=$(git -C "$d" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  fi
done
echo "=== rescue done $(date '+%F %T') ==="
