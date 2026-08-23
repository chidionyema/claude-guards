#!/bin/bash
# Move ~/Documents/code -> ~/dev/code, one directory at a time.
#
# Default is REPORT. It changes nothing until --apply is passed.
# Every rename is recorded in the manifest BEFORE it runs, so an interrupted
# run can be read and resumed instead of guessed at.
#
# Why not one mv: ~/dev/code already exists and is populated, so a single
# rename would land the tree at ~/dev/code/code. This is ~54 renames, which
# means partial states are reachable and the manifest is not optional.

set -u
SRC="$HOME/Documents/code"
DST="$HOME/dev/code"
MAN="$HOME/dev/migration/manifest.tsv"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

say() { printf '%s\n' "$*"; }
hdr() { say ""; say "=== $* ==="; }

# ── preflight: refuse to start if any of these is not true ────────────────────
hdr "PREFLIGHT"
fail=0
chk() { if eval "$2" >/dev/null 2>&1; then say "  OK    $1"; else say "  FAIL  $1"; fail=1; fi; }

chk "source exists"                 "[ -d '$SRC' ]"
chk "target parent exists"          "[ -d '$HOME/dev' ]"
chk "same volume (rename, no copy)" "[ \"\$(stat -f %d '$SRC')\" = \"\$(stat -f %d '$HOME/dev')\" ]"
chk "safety bundles present"        "ls -d $HOME/dev/backup/pre-move-*/ "
chk "no name collisions"            "[ -z \"\$(comm -12 <(ls -1 '$SRC'|sort) <(ls -1 '$DST'|sort))\" ]"

# Another session must not be sitting inside the tree.
# Exclude this script's own process tree, or it reports itself and never runs.
mypids=$(ps -o pid=,ppid=,pgid= -A 2>/dev/null | awk -v g="$(ps -o pgid= -p $$ | tr -d ' ')" '$3==g{print $1}')
inuse=$(lsof -a -d cwd -- "$SRC" 2>/dev/null | awk 'NR>1{print $2"\t"$1}' | sort -u \
        | grep -vwFf <(printf '%s\n' $mypids) 2>/dev/null \
        | awk '{print $2" pid="$1}')
if [ -n "$inuse" ]; then
  say "  FAIL  a process has its cwd inside $SRC:"
  say "$inuse" | sed 's/^/          /'
  fail=1
else
  say "  OK    no process has its cwd inside the tree"
fi

# Report mode changes nothing, so a failed preflight should still print the
# plan. Only --apply is stopped by it.
if [ "$fail" = 1 ]; then
  say ""
  if [ "$APPLY" = 1 ]; then say "PREFLIGHT FAILED — nothing attempted."; exit 1; fi
  say "PREFLIGHT FAILED — --apply would stop here. Showing the plan anyway."
fi

# ── manifest ──────────────────────────────────────────────────────────────────
hdr "CLOCK"
# This machine is running ~21.6 h behind real time (measured 2026-08-22 against
# Cloudflare, GitHub and Apple Date headers, all agreeing within 15 s). Every
# timestamp below, and every commit made today, is stamped about a day early.
# Do not trust a date in this manifest; trust the order.
say "  local now:  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
_rd=$(curl -sI --max-time 10 https://www.cloudflare.com 2>/dev/null | awk 'tolower($1)=="date:"{sub(/^[Dd]ate: /,"");print}')
say "  endpoint:   ${_rd:-<unreachable>}"
say "  NOTE: local is ~21.6 h behind. Dates in this manifest are wrong by that much."

hdr "MANIFEST"
mkdir -p "$HOME/dev/migration"
if [ "$APPLY" = 1 ]; then : > "$MAN"; fi
n=0
for d in "$SRC"/*/; do
  d=${d%/}; b=$(basename "$d")
  if   [ -f "$d/.git" ]; then k=worktree
  elif [ -d "$d/.git" ]; then k=repo
  else k=plain; fi
  n=$((n+1))
  printf "  %-32s %-9s -> %s\n" "$b" "$k" "$DST/$b"
  [ "$APPLY" = 1 ] && printf "%s\t%s\t%s\t%s\tPENDING\n" "$b" "$k" "$d" "$DST/$b" >> "$MAN"
done
say "  $n directories"
[ "$APPLY" = 1 ] && say "  manifest written: $MAN"

# ── the renames ───────────────────────────────────────────────────────────────
hdr "RENAME"
if [ "$APPLY" = 0 ]; then
  say "  REPORT MODE — nothing moved. Re-run with --apply."
else
  while IFS=$'\t' read -r b k from to st; do
    [ "$st" = PENDING ] || continue
    if mv -n "$from" "$to" 2>/dev/null && [ -d "$to" ]; then
      sed -i '' "s#^${b}\t${k}\t.*\tPENDING\$#${b}\t${k}\t${from}\t${to}\tMOVED#" "$MAN"
      say "  moved   $b"
    else
      say "  FAILED  $b — stopping so the manifest stays true"
      exit 1
    fi
  done < "$MAN"
fi

# ── repair, in the order that matters ─────────────────────────────────────────
hdr "REPAIR PLAN (run order)"
say "  1. repoint the symlink. Measured 2026-08-22: 13 of the 16 affected plists"
say "     name ~/.hermes, but only 6 name it EXCLUSIVELY. The other 7 also carry a"
say "     direct /Documents/code/ path, so the symlink alone leaves them half-fixed:"
say "       graphify-sweep, reflect, prospector.backup, prospector.estate-inventory,"
say "       prospector.launchd-held, prospector.process-audit, signalengine.daemon"
say "     3 more name only the direct path and the symlink does nothing for them:"
say "       prospector.log-rotation, prospector.offsite-backup, prospector.scheduler"
say "     The direct paths in those 7 are NOT hermes. They are prospector (20),"
say "     prospector-live (11) and signalengine (2). No plist anywhere names"
say "     /Documents/code/hermes directly; every hermes reference goes via the"
say "     symlink. That is why a hermes-only grep reports 13 and 0, and a"
say "     whole-tree grep reports 10 direct. 13 + 10 - 7 overlap = 16 by grep."
say "     15 by resolution. ai.hermes.gateway.plist matches only on line 6, which"
say "     is its own Label and not a path. Every path it declares is outside"
say "     Documents and it is not loaded. Reload 15, not 16."
say "     Verify with ~/.claude/scripts/estate/launchd_documents.py, which resolves"
say "     declared paths instead of grepping and passes on a repoint."
say "     So step 1 and step 4 are both mandatory. Neither is sufficient alone."
say "       ln -sfn $DST/hermes $HOME/.hermes"
say "  2. git worktree repair, from each parent repo"
for p in prospector prospector-live; do say "       git -C $DST/$p worktree repair"; done
say "  3. rebuild the 4 real venvs. A venv bakes absolute paths into pyvenv.cfg"
say "     and every console-script shebang, so it cannot be moved, only rebuilt."
say "     Only 4 of the 40 .venv entries are real directories. 32 are symlinks to"
say "     prospector/.venv and survive the move because their target moves with"
say "     them. The other 4 point into iCloud and are a separate problem:"
say "       wt-automerge-sweep wt-incidents wt-integrate wt-storefront"
say "       -> .venv -> ~/Library/Mobile Documents/.../code/prospector/.venv"
say "     Those 4 keep working after the move and keep using the STALE iCloud copy."
say "     Repoint them at the moved tree or they silently diverge."
say ""
say "     pip is absent from all 4 real venvs, so pip freeze returns nothing. The"
say "     pinned lists were reconstructed from .dist-info directory names and are"
say "     in ~/dev/migration/requirements/ (115, 105, 81 and 23 packages)."
for v in sentinel-loop hermes-v2.ARCHIVED.20260822 prospector signalengine; do
  say "       rm -rf $DST/$v/.venv && python3 -m venv $DST/$v/.venv"
  say "       $DST/$v/.venv/bin/pip install -r ~/dev/migration/requirements/$v.txt"
done
say ""
say "  4. rewrite the plists that name the old path (10 files: the 3 direct + the 7 both)"
say "       sed -i '' 's#/Documents/code/#/dev/code/#g' ~/Library/LaunchAgents/*.plist"
say "  5. reload every loaded job — launchctl runs the definition it loaded at"
say "     bootstrap, NOT the plist on disk, so an unreloaded job keeps the old"
say "     path and still reports exit 0. Verify each one, do not spot check."
say "       launchctl bootout    gui/501/<label>"
say "       launchctl bootstrap  gui/501 ~/Library/LaunchAgents/<label>.plist"
say "       launchctl print      gui/501/<label> | grep -c Documents/code   # must be 0"

say "  6. verify the import-path callers. Three scripts reach into the tree with"
say "     sys.path rather than a plist path, so no path grep of the plists finds"
say "     them. They survive only because step 1 repoints the symlink."
say "       ~/.claude/scripts/estate/estate_cost_sentinel.py:44   sys.path.insert"
say "       ~/.claude/scripts/estate/estate_push.sh:52            sys.path.insert"
say "       ~/.claude/scripts/estate/estate_watch.py:52           sys.path.append"
say "     Two more read credentials from the tree, both declared fallbacks:"
say "       ~/.claude/scripts/estate/estate_push.sh:44   ENVFILE=~/.hermes/.env"
say "       ~/.claude/scripts/estate/estate_alert.py:25  HERMES_HOME"
say "     Prove each imports after the move, do not assume the symlink covered it:"
say "       python3 -c \"import sys,os; sys.path.insert(0,os.path.expanduser('~/.hermes/scripts')); import telegram_ledger; print(telegram_ledger.__file__)\""
say ""
