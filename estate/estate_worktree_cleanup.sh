#!/usr/bin/env bash
# estate_worktree_cleanup.sh — retire the prospector worktrees whose branch is already
# in origin/main, after saving anything they hold that exists nowhere else.
#
# WHY. Founder, 2026-08-23: "a lot of the repos are stale and need cleaning up not
# workig around". Measured the same day under ~/Documents/code: 34 wt-* directories,
# all sharing one object store (prospector/.git). 18 of them sit on a commit that
# origin/main already contains, so the branch work is done. Backing those up hourly
# forever is the working around; this removes them.
#
# WHY NOT rm -rf. Every one of those 18 also carries uncommitted edits, from 1 added
# line in wt-swt to 13,783 in wt-mainred. Those edits are in no commit and on no
# remote, so deleting the directory destroys the only copy. This captures them first.
#
# WHAT IT CAPTURES, per worktree:
#   diff.patch     git diff HEAD, every uncommitted change to a tracked file
#   untracked.txt  the path of every untracked file git would not ignore
#   untracked.tar  those files, when they fit under the cap (see SALVAGE_MAX_MB)
#   head.txt       the commit the worktree sat on, so the patch can be replayed
# The capture is tarred, pushed to R2 next to the bundles, and read back and compared
# byte for byte before a single directory is touched.
#
# REPORT MODE IS THE DEFAULT. With no arguments this measures, captures, uploads and
# prints what it would remove. It removes nothing. Pass --apply to remove.
#
# RESTORE. rclone cat :s3:$R2_BUCKET/salvage/latest.tar.gz | tar xz -C /tmp
# then, in a fresh worktree at head.txt's commit: git apply diff.patch
set -uo pipefail

export PATH="${PATH:-}:/Users/chidionyema/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO="${ESTATE_WT_REPO:-$HOME/Documents/code/prospector}"
STATE="$HOME/.claude/state"
RECEIPTS="$STATE/estate-worktree-cleanup.jsonl"
ENVFILE="$HOME/.config/estate/estate.env"
[ -r "$ENVFILE" ] || ENVFILE="$HOME/.hermes/.env"
SALVAGE_MAX_MB=${ESTATE_SALVAGE_MAX_MB:-50}
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
WORK="${TMPDIR:-/tmp}/estate-wt-salvage.$$"
mkdir -p "$WORK/salvage" "$STATE"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
die() { log "WORKTREE CLEANUP RED: $*"; exit 1; }

# --- credentials, into this process only, never into argv --------------------
getenv() {
  eval "v=\${$1:-}"
  [ -n "$v" ] && { printf %s "$v"; return; }
  awk -F= -v k="$1" '$1==k{sub(/^[^=]*=/,"");gsub(/^["'"'"']|["'"'"']$/,"");print;exit}' "$ENVFILE" 2>/dev/null
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
[ -n "$RCLONE_S3_SECRET_ACCESS_KEY" ] || die "R2 credentials missing from $ENVFILE"
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || die "$REPO is not a git repository"
ls "$REPO" >/dev/null 2>&1 || die "cannot list $REPO — this process is denied that directory"

git -C "$REPO" fetch origin --quiet 2>/dev/null || log "warning: fetch failed, merged status is judged against a possibly stale origin/main"
git -C "$REPO" rev-parse --verify origin/main >/dev/null 2>&1 || die "origin/main does not exist locally, nothing to judge merged against"

# --- classify -----------------------------------------------------------------
REMOVABLE=""; KEPT=0; SALVAGED=0
while IFS= read -r w; do
  [ -n "$w" ] || continue
  [ "$w" = "$REPO" ] && continue
  name=$(basename "$w")
  [ -d "$w" ] || { log "skip $name — registered but the directory is gone, worktree prune will clear it"; continue; }

  head=$(git -C "$w" rev-parse HEAD 2>/dev/null) || { log "skip $name — no HEAD"; continue; }
  if ! git -C "$REPO" merge-base --is-ancestor "$head" origin/main 2>/dev/null; then
    KEPT=$((KEPT+1)); log "keep $name — its commit is not in origin/main, the work is unmerged"; continue
  fi

  # merged. Save whatever is uncommitted before it is allowed to be removed.
  out="$WORK/salvage/$name"; mkdir -p "$out"
  printf '%s\n' "$head" > "$out/head.txt"
  git -C "$w" rev-parse --abbrev-ref HEAD > "$out/branch.txt" 2>/dev/null
  git -C "$w" diff HEAD > "$out/diff.patch" 2>/dev/null
  git -C "$w" ls-files --others --exclude-standard > "$out/untracked.all" 2>/dev/null

  # Untracked means git was never told to ignore it, and that is exactly where a live
  # .env or a private key sits. Measured on the first report run: wt-cardsub listed
  # .env and .lux/keys/agent.pem among 2,852 untracked files. They escaped upload only
  # because that worktree happened to be over the size cap, which is luck, not a rule.
  # Refuse them by name, and say how many were refused rather than dropping them quietly.
  grep -ivE '(^|/)\.env($|\.)|(^|/)id_(rsa|ed25519|ecdsa)$|\.(pem|key|p12|pfx|jks|der)$|(^|/)\.netrc$|(^|/)credentials$' \
    "$out/untracked.all" > "$out/untracked.txt" 2>/dev/null || : > "$out/untracked.txt"
  refused=$(( $(wc -l < "$out/untracked.all" | tr -d ' ') - $(wc -l < "$out/untracked.txt" | tr -d ' ') ))
  if [ "$refused" -gt 0 ]; then
    log "note $name — $refused untracked file(s) look like key material by filename and are NOT archived"
    grep -iE '(^|/)\.env($|\.)|(^|/)id_(rsa|ed25519|ecdsa)$|\.(pem|key|p12|pfx|jks|der)$|(^|/)\.netrc$|(^|/)credentials$' \
      "$out/untracked.all" > "$out/untracked.REFUSED-key-material" 2>/dev/null
  fi
  rm -f "$out/untracked.all"

  ucount=$(wc -l < "$out/untracked.txt" | tr -d ' ')
  if [ "$ucount" -gt 0 ]; then
    ubytes=$( (cd "$w" && tr '\n' '\0' < "$out/untracked.txt" | xargs -0 stat -f %z 2>/dev/null) | awk '{s+=$1} END{print s+0}')
    if [ "$ubytes" -le $((SALVAGE_MAX_MB * 1024 * 1024)) ]; then
      (cd "$w" && tar czf "$out/untracked.tar.gz" -T "$out/untracked.txt" 2>/dev/null) \
        || log "note $name — some untracked files could not be archived, untracked.txt still lists them"
    else
      # No silent cap. Say what was left behind and how big it was.
      log "note $name — $ucount untracked file(s) total $((ubytes/1024/1024)) MB, over the ${SALVAGE_MAX_MB} MB cap, so only the path list is saved"
      printf 'NOT ARCHIVED: %s bytes across %s files, over the %s MB cap\n' "$ubytes" "$ucount" "$SALVAGE_MAX_MB" > "$out/untracked.SKIPPED"
    fi
  fi

  ins=$(grep -c '^+' "$out/diff.patch" 2>/dev/null || echo 0)
  SALVAGED=$((SALVAGED+1))
  REMOVABLE="$REMOVABLE $w"
  log "salvaged $name — merged, ${ins} added line(s) captured, $ucount untracked file(s) listed"
done <<EOF
$(git -C "$REPO" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2}')
EOF

if [ "$SALVAGED" -eq 0 ]; then
  log "WORKTREE CLEANUP GREEN  nothing merged to retire, $KEPT worktree(s) still carry unmerged work"
  exit 0
fi

# --- push the salvage, and prove it comes back --------------------------------
ARCHIVE="$WORK/worktree-salvage-$STAMP.tar.gz"
(cd "$WORK" && tar czf "$ARCHIVE" salvage) || die "could not build the salvage archive"
SZ=$(( $(stat -f %z "$ARCHIVE") / 1024 ))

rclone copyto "$ARCHIVE" ":s3:$R2_BUCKET/salvage/$STAMP.tar.gz" --s3-no-check-bucket \
  || die "salvage upload failed, so nothing will be removed"
rclone copyto "$ARCHIVE" ":s3:$R2_BUCKET/salvage/latest.tar.gz" --s3-no-check-bucket \
  || die "salvage upload of latest failed, so nothing will be removed"

LOCAL_SHA=$(shasum -a 256 "$ARCHIVE" | cut -d' ' -f1)
BACK="$WORK/readback.tar.gz"
rclone cat ":s3:$R2_BUCKET/salvage/latest.tar.gz" > "$BACK" 2>/dev/null || die "readback download failed, nothing will be removed"
REMOTE_SHA=$(shasum -a 256 "$BACK" | cut -d' ' -f1)
[ "$LOCAL_SHA" = "$REMOTE_SHA" ] || die "readback mismatch, nothing will be removed"
tar tzf "$BACK" >/dev/null 2>&1 || die "the archive that came back does not open, nothing will be removed"
log "salvage pushed ${SZ} KB  key=salvage/latest.tar.gz  readback=identical and opens"

printf '{"ts":%s,"iso":"%s","stamp":"%s","salvaged":%s,"kept":%s,"kb":%s,"sha256":"%s","applied":%s}\n' \
  "$(date +%s)" "$(date -u +%FT%TZ)" "$STAMP" "$SALVAGED" "$KEPT" "$SZ" "$LOCAL_SHA" "$APPLY" >> "$RECEIPTS"

# --- remove, only with --apply ------------------------------------------------
if [ "$APPLY" = 0 ]; then
  log "REPORT ONLY. $SALVAGED merged worktree(s) are saved and ready to retire, $KEPT kept:"
  for w in $REMOVABLE; do log "  would remove $w"; done
  log "run again with --apply to remove them"
  exit 0
fi

REMOVED=0; FAILED=0
for w in $REMOVABLE; do
  if git -C "$REPO" worktree remove --force "$w" 2>/dev/null; then
    REMOVED=$((REMOVED+1)); log "removed $(basename "$w")"
  else
    FAILED=$((FAILED+1)); log "could not remove $(basename "$w") — left in place"
  fi
done
git -C "$REPO" worktree prune 2>/dev/null

if [ "$FAILED" -gt 0 ]; then
  log "WORKTREE CLEANUP RED  removed $REMOVED, failed $FAILED, kept $KEPT — salvage is in R2 either way"
  exit 1
fi
log "WORKTREE CLEANUP GREEN  removed $REMOVED merged worktree(s), kept $KEPT unmerged, salvage=salvage/latest.tar.gz"
