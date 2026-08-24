#!/bin/sh
# Source this to get a working restic environment for the estate repo.
# Secrets stay in ~/.config/estate/estate.env and ~/.estate/restic/password;
# this file names them and never contains them (LAW 21, LAW 24).
set -a
. "$HOME/.config/estate/estate.env"
set +a
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RESTIC_REPOSITORY="s3:https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com/${R2_BUCKET}/restic"
export RESTIC_PASSWORD_FILE="$HOME/.estate/restic/password"
