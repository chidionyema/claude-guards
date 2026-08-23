#!/usr/bin/env bash
# estate_bundle_push.sh — get every commit that exists only on this Mac off this Mac.
#
# WHY. Measured 2026-08-23, after a fetch of every remote so the count is honest:
# 21 commits in ~/.claude exist on no remote and that repo HAS no remote. That is the
# whole control plane, from its first commit onward. Four more repos are in the same
# state (maestro 3, code 2, my-ebook-store 1, AwesomeProject 1), and ten repos that do
# have a remote carry work that was never pushed to it. One disk failure loses all of it.
#
# WHY NOT backup_agent_estate.py. That script exists, is careful, and does not close
# this. Its allow-list has no `.git`, so it copies a working tree and no history; it
# writes to a local --out path and uploads nowhere; it is on no schedule; and it has
# never produced a receipt on this machine. A backup nobody runs is LAW 28's exact case.
#
# WHY NOT `git push`. Pushing somebody's half-finished branch to a shared remote is a
# decision about what other people see, and it is not reversible by me. A bundle is a
# copy: it changes nothing, it needs no repo-visibility ruling from the founder, and
# `git clone the.bundle` restores it.
#
# WHAT IT PUSHES. For a repo with no remote, `--all`: every ref, whole history, because
# there is no other copy anywhere. For a repo that has a remote, only what the remote
# does not have (`--all --not --remotes`), which is a few hundred KB instead of a
# gigabyte. LIMITATION, written down so the next agent inherits it instead of finding
# it: restoring one of those incremental bundles needs the remote as well as the bundle.
# That is the correct trade while the remote exists; it is not a full escrow of GitHub.
#
# WHY THE READBACK AND THE CLONE. "rclone said ok" is one angle (LAW 15). This
# re-downloads the bytes and compares sha256, then clones the downloaded copy into a
# temp directory and checks the tip commit matches. A backup is proven by a restore,
# not by an upload, and the restore runs every time the upload does.
#
# SECRETS. rclone is configured through RCLONE_S3_* environment variables, never flags,
# so nothing reaches argv where `ps` can read it. A repo whose history contains a file
# matching key material is REFUSED, loudly, rather than shipped.
set -uo pipefail

# launchd hands a job almost no environment, and the first run under it died on
# "rclone is not installed" while the identical command passed by hand. The proven
# com.founder.estatepush job sets this in its plist; this line means the script does
# not depend on whoever calls it remembering to.
export PATH="${PATH:-}:/Users/chidionyema/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

STATE="$HOME/.claude/state"
RECEIPTS="$STATE/estate-bundle-push.jsonl"
WORK="${TMPDIR:-/tmp}/estate-bundles.$$"
ENVFILE="$HOME/.config/estate/estate.env"
[ -r "$ENVFILE" ] || ENVFILE="$HOME/.hermes/.env"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

#: Roots to search. Three levels deep covers ~/Documents/code/<repo>/.git and no more.
ROOTS=("$HOME/.claude" "$HOME/.maestro" "$HOME/Documents/code" "$HOME/dev/code" "$HOME/code")

#: A bundle larger than this is reported and skipped rather than silently uploaded.
#: No silent caps (LAW 28): a skip prints and lands in the receipt.
MAX_MB=${ESTATE_BUNDLE_MAX_MB:-250}

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "BUNDLE PUSH RED: $*"; alert "estate_bundle_push RED: $* — commits that exist only on this Mac are still only on this Mac."; rm -rf "$WORK"; exit 1; }

alert() {
  python3 - "$1" <<'PY' 2>/dev/null || true
import os, sys
# This script's own directory first. ~/.hermes is retired and is a symlink into
# ~/Documents, which macOS TCC hides from a bootstrapped LaunchAgent; putting it at
# sys.path[0] is what made estate_cost_sentinel import the dead tree's copy.
sys.path.insert(0, os.path.expanduser("~/.claude/scripts/estate"))
try:
    import estate_alert
except Exception as exc:
    print(f"[bundle-push] alerting unavailable: {exc!r}", file=sys.stderr)
    raise SystemExit(0)
estate_alert.send_operator_alert(sys.argv[1], debounce_key="estate-bundle-push", debounce_s=3600)
PY
}

# --- credentials, read into this process only -------------------------------
getenv() {
  eval "v=\${$1:-}"
  [ -n "$v" ] && { printf %s "$v"; return; }
  awk -F= -v k="$1" '$1==k{sub(/^[^=]*=/,"");gsub(/^["'"'"']|["'"'"']$/,"");print;exit}' "$ENVFILE"
}
R2_ACCOUNT_ID=$(getenv R2_ACCOUNT_ID)
R2_BUCKET=$(getenv R2_BUCKET); R2_BUCKET="${R2_BUCKET:-prospector-packs}"
export RCLONE_CONFIG=/dev/null
export RCLONE_S3_PROVIDER=Other
export RCLONE_S3_REGION=auto
export RCLONE_S3_FORCE_PATH_STYLE=true
export RCLONE_S3_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
export RCLONE_S3_ACCESS_KEY_ID=$(getenv R2_ACCESS_KEY_ID)
export RCLONE_S3_SECRET_ACCESS_KEY=$(getenv R2_SECRET_ACCESS_KEY)

command -v rclone >/dev/null || die "rclone is not installed"
[ -n "$R2_ACCOUNT_ID" ] || die "R2_ACCOUNT_ID missing from $ENVFILE"
[ -n "$RCLONE_S3_SECRET_ACCESS_KEY" ] || die "R2 credentials missing from $ENVFILE"

mkdir -p "$WORK" "$STATE" || die "cannot create $WORK"
DAY=$(date -u +%Y-%m-%d); STAMP=$(date -u +%Y%m%dT%H%M%SZ)

# --- which repos, deduplicated by object store ------------------------------
# Every wt-* directory under ~/Documents/code is a git WORKTREE of prospector and
# reports prospector's own .git as its common dir. Bundling each one would upload the
# same 495 commits thirty times.
# --- every declared root must be READABLE, or this job is lying --------------
# Measured 2026-08-23. By hand this found 19 repos; bootstrapped by launchd it found 10
# and printed GREEN. The nine it lost were every repo under ~/Documents, which macOS TCC
# hides from a bootstrapped LaunchAgent:
#
#     ls: /Users/chidionyema/Documents/code: Operation not permitted
#
# A backup that silently covers half of what it is asked to cover is worse than none,
# because the receipt reads as complete. So a root that cannot be listed is RED.
#
# The test is a real listing, not `test -r`. Under that denial `test -d` answers yes and
# `test -r` answers yes; only an actual read fails. A guard built on -r passes exactly
# when it is needed.
denied=""
for root in "${ROOTS[@]}"; do
  [ -d "$root" ] || continue                       # not on this machine, nothing to cover
  ls "$root" >/dev/null 2>&1 || denied="$denied $root"
done
# A denied root is dropped from the search and the run ends RED. Aborting outright was
# the first version and it was wrong: it left ~/.claude, which is readable and is the one
# repo with no remote at all, with no hourly backup because a DIFFERENT root was blocked.
# Cover what is reachable, and be loud about what is not.
DENIED_ROOTS="$denied"
if [ -n "$DENIED_ROOTS" ]; then
  log "DENIED:$DENIED_ROOTS — not listable by this process, every repo under there is skipped"
  keep=()
  for root in "${ROOTS[@]}"; do
    case " $DENIED_ROOTS " in *" $root "*) continue ;; esac
    keep+=("$root")
  done
  ROOTS=("${keep[@]}")
  [ "${#ROOTS[@]}" -gt 0 ] || die "every declared root is unreadable by this process"
fi

find "${ROOTS[@]}" -maxdepth 3 -name .git -print 2>/dev/null | sed 's|/\.git$||' | sort -u \
  > "$WORK/candidates.txt"

: > "$WORK/plan.tsv"
seen_common=""
while read -r d; do
  common=$(git -C "$d" rev-parse --git-common-dir 2>/dev/null) || continue
  case "$common" in /*) ;; *) common="$d/$common" ;; esac
  common=$(cd "$common" 2>/dev/null && pwd -P) || continue
  case "$seen_common" in *"|$common|"*) continue ;; esac
  seen_common="$seen_common|$common|"

  remote=$(git -C "$d" remote | head -1)
  if [ -n "$remote" ]; then
    n=$(git -C "$d" rev-list --count --all --not --remotes 2>/dev/null || echo 0)
    mode=incremental
    # A remote-tracking ref proves a remote answered ONCE, not that it answers now.
    # Measured 2026-08-23: 13 repos under ~/code point at dev.azure.com/OSLSoftware,
    # a former client's server. Every one reported 0 commits no remote has, so every
    # one was skipped, and not one of them can be cloned back. The cached ref was
    # reporting safety on behalf of a server that is gone.
    #
    # Only asked when the count is 0, which is exactly when the answer changes what
    # happens, so the hourly job pays one ls-remote per otherwise-skipped repo.
    if [ "${n:-0}" -eq 0 ]; then
      if ! GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/usr/bin/true \
           timeout 15 git -C "$d" ls-remote --exit-code "$remote" HEAD >/dev/null 2>&1; then
        n=$(git -C "$d" rev-list --count --all 2>/dev/null || echo 0)
        mode=full-unreachable-remote
        log "unreachable: $(basename "$d") points at $remote which does not answer, so its $n commit(s) exist only on this disk"
      fi
    fi
  else
    n=$(git -C "$d" rev-list --count --all 2>/dev/null || echo 0)
    mode=full
  fi
  [ "${n:-0}" -gt 0 ] || continue
  printf '%s\t%s\t%s\t%s\n' "$d" "$mode" "$n" "${remote:-NO-REMOTE}" >> "$WORK/plan.tsv"
done < "$WORK/candidates.txt"

PLANNED=$(wc -l < "$WORK/plan.tsv" | tr -d ' ')
log "at risk: $PLANNED repo(s) carry commits no remote has"
[ "$PLANNED" -gt 0 ] || { log "BUNDLE PUSH GREEN  nothing at risk"; rm -rf "$WORK"; exit 0; }

if [ "$DRY" = 1 ]; then
  log "DRY RUN. would bundle and push to :s3:$R2_BUCKET/bundles/<repo>/"
  awk -F'\t' '{printf "  %-28s %-12s %5s commit(s)  remote=%s\n",$1,$2,$3,$4}' "$WORK/plan.tsv"
  log "bucket reachable? $(rclone lsd ":s3:$R2_BUCKET" >/dev/null 2>&1 && echo yes || echo NO)"
  rm -rf "$WORK"; exit 0
fi

# --- bundle, push, read back, restore ---------------------------------------
OK=0; FAILED=0; SKIPPED=0
while IFS=$'\t' read -r d mode n remote; do
  slug=$(printf %s "${d#$HOME/}" | tr '/' '-' | tr -cd 'A-Za-z0-9._-')
  bundle="$WORK/$slug.bundle"

  # LAW 21. A file whose NAME is key material is refused rather than shipped. This is
  # the cheap decisive control; the receipt says plainly that contents were not scanned,
  # so nobody later reads this as a clean bill of health for the bytes inside.
  if git -C "$d" log --all --name-only --pretty=format: 2>/dev/null \
       | grep -qiE '(^|/)(\.env|id_rsa|id_ed25519|id_ecdsa)|\.(pem|key|p12|pfx|jks|der)$'; then
    log "REFUSED $slug — its history contains key material by filename; not uploading"
    SKIPPED=$((SKIPPED+1))
    printf '{"ts":%s,"iso":"%s","repo":"%s","outcome":"refused-key-material"}\n' \
      "$(date +%s)" "$(date -u +%FT%TZ)" "$d" >> "$RECEIPTS"
    continue
  fi

  if [ "$mode" = full ]; then
    git -C "$d" bundle create "$bundle" --all >/dev/null 2>&1
  else
    git -C "$d" bundle create "$bundle" --all --not --remotes >/dev/null 2>&1
  fi
  [ -s "$bundle" ] || { log "FAILED $slug — git bundle produced nothing"; FAILED=$((FAILED+1)); continue; }

  bytes=$(stat -f %z "$bundle")
  if [ "$bytes" -gt $((MAX_MB * 1048576)) ]; then
    log "SKIPPED $slug — bundle is $((bytes/1048576)) MB, over the ${MAX_MB} MB ceiling. Raise ESTATE_BUNDLE_MAX_MB or push the branch."
    SKIPPED=$((SKIPPED+1)); rm -f "$bundle"; continue
  fi

  # A bundle git itself will not open is not a backup. Checked before it is uploaded.
  git -C "$d" bundle verify "$bundle" >/dev/null 2>&1 \
    || { log "FAILED $slug — git bundle verify refused the file it just wrote"; FAILED=$((FAILED+1)); rm -f "$bundle"; continue; }

  key="bundles/$slug"
  rclone copyto "$bundle" ":s3:$R2_BUCKET/$key/$DAY/$STAMP.bundle" --s3-no-check-bucket 2>/dev/null \
    || { log "FAILED $slug — dated upload failed"; FAILED=$((FAILED+1)); rm -f "$bundle"; continue; }
  rclone copyto "$bundle" ":s3:$R2_BUCKET/$key/latest.bundle" --s3-no-check-bucket 2>/dev/null \
    || { log "FAILED $slug — latest upload failed"; FAILED=$((FAILED+1)); rm -f "$bundle"; continue; }

  # Angle two: the bytes come back identical.
  local_sha=$(shasum -a 256 "$bundle" | cut -d' ' -f1)
  back="$WORK/$slug.readback"
  rclone cat ":s3:$R2_BUCKET/$key/latest.bundle" > "$back" 2>/dev/null
  remote_sha=$(shasum -a 256 "$back" | cut -d' ' -f1)
  if [ "$local_sha" != "$remote_sha" ]; then
    log "FAILED $slug — readback mismatch"; FAILED=$((FAILED+1)); rm -f "$bundle" "$back"; continue
  fi

  # Angle three, and the only one that is a restore: clone the DOWNLOADED copy and
  # check its tip is the commit this repo is on. A full bundle clones standalone; an
  # incremental one cannot, by construction, so it is verified against this repo.
  tip=$(git -C "$d" rev-parse HEAD 2>/dev/null)
  drill=skipped
  if [ "$mode" = full ]; then
    if git clone --quiet "$back" "$WORK/restore-$slug" >/dev/null 2>&1 \
       && [ "$(git -C "$WORK/restore-$slug" rev-parse HEAD 2>/dev/null)" = "$tip" ]; then
      drill=clone-ok
    else
      log "FAILED $slug — the uploaded bundle does not clone back to $tip"; FAILED=$((FAILED+1))
      rm -rf "$bundle" "$back" "$WORK/restore-$slug"; continue
    fi
  else
    if git -C "$d" bundle verify "$back" >/dev/null 2>&1; then drill=verify-ok; else
      log "FAILED $slug — the downloaded bundle does not verify"; FAILED=$((FAILED+1))
      rm -f "$bundle" "$back"; continue
    fi
  fi

  printf '{"ts":%s,"iso":"%s","repo":"%s","slug":"%s","mode":"%s","commits":%s,"remote":"%s","bytes":%s,"sha256":"%s","tip":"%s","restore":"%s","contents_scanned":false}\n' \
    "$(date +%s)" "$(date -u +%FT%TZ)" "$d" "$slug" "$mode" "$n" "$remote" "$bytes" "$local_sha" "$tip" "$drill" >> "$RECEIPTS"
  log "pushed $slug  $mode  $n commit(s)  $((bytes/1024)) KB  restore=$drill"
  OK=$((OK+1))
  rm -rf "$bundle" "$back" "$WORK/restore-$slug"
done < "$WORK/plan.tsv"

rm -rf "$WORK"

if [ "$FAILED" -gt 0 ]; then
  log "BUNDLE PUSH RED  ok=$OK failed=$FAILED skipped=$SKIPPED"
  alert "estate_bundle_push: $FAILED repo(s) failed to reach R2. ok=$OK skipped=$SKIPPED. Commits with no other copy are still on one disk."
  exit 1
fi
if [ -n "$DENIED_ROOTS" ]; then
  log "BUNDLE PUSH RED  repos=$OK skipped=$SKIPPED  but$DENIED_ROOTS could not be listed, so every repo under there is UNCOVERED by this run"
  alert "estate_bundle_push: covered $OK repo(s), but$DENIED_ROOTS is not readable by this job, so nothing under it is backed up. macOS TCC hides it from a bootstrapped LaunchAgent. One fix, once: grant Full Disk Access to /bin/bash in System Settings."
  exit 1
fi
log "BUNDLE PUSH GREEN  bucket=$R2_BUCKET  repos=$OK  skipped=$SKIPPED  key=bundles/<repo>/latest.bundle  restore=git clone <bundle>"
[ "$SKIPPED" -gt 0 ] && exit 2
exit 0
