#!/bin/sh
# (Re)create the estate-healthchecks container from its on-disk config.
# Data survives: the sqlite DB lives in ~/.estate/healthchecks/data on the host.
# Env values live in ~/.estate/healthchecks/hc.env and are never committed (LAW 21).
# docker restart does NOT re-read the env-file; a config change needs this script.
set -eu
HC=~/.estate/healthchecks
docker rm -f estate-healthchecks 2>/dev/null || true
docker run -d --name estate-healthchecks \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --env-file "$HC/hc.env" \
  -v "$HC/data:/data" \
  healthchecks/healthchecks:latest
# Django takes ~60s to serve after start.
for i in $(seq 1 24); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000 || true)
  case "$code" in 200|302) echo "healthchecks serving (http $code) after ~$((i*5))s"; exit 0;; esac
  sleep 5
done
echo "healthchecks NOT serving after 120s" >&2
exit 1
