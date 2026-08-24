#!/bin/sh
# Source this to get a working restic environment for the estate repo.
# Secrets stay in ~/.config/estate/estate.env and ~/.estate/restic/password;
# this file names them and never contains them (LAW 21, LAW 24).
#
# launchd's default environment is PATH=/usr/bin:/bin:/usr/sbin:/sbin — it
# does not read .zshrc/.zprofile, so a Homebrew-installed binary (restic at
# /usr/local/bin/restic, measured 2026-08-24) is invisible to any job that
# does not set PATH itself. Every script sourcing this file inherits a
# working PATH instead of failing exit 127 on its first scheduled run.
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
set -a
. "$HOME/.config/estate/estate.env"
set +a
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RESTIC_REPOSITORY="s3:https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com/${R2_BUCKET}/restic"
export RESTIC_PASSWORD_FILE="$HOME/.estate/restic/password"
