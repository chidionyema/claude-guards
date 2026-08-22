#!/usr/bin/env bash
# One command, from anywhere, for the consult service.
#
# The harness itself lives in the repo it verifies, at hermes-v2/bin/verify-consult,
# so it travels with the code and runs on a pull request. This is the estate-wide
# handle onto it, because a founder on a phone should not have to remember a
# repo path to ask whether his own service is up.
set -uo pipefail
REPO="${HERMES_V2:-$HOME/Documents/code/hermes-v2}"
if [ ! -x "$REPO/bin/verify-consult" ]; then
  echo "consult-verify: no harness at $REPO/bin/verify-consult" >&2
  echo "  set HERMES_V2 to the checkout, or clone https://github.com/chidionyema/hermes-v2" >&2
  exit 2
fi
exec "$REPO/bin/verify-consult" "$@"
