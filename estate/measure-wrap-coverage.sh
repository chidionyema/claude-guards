#!/bin/sh
# Is a job wrapped? The plist grep is a PROXY: a plist may call a script that itself
# calls hc-wrap. Grade the transitive fact, not the file that happens to be easy to read.
LA="$HOME/Library/LaunchAgents"
direct=0; indirect=0; bare=0; total=0
for l in $(launchctl list 2>/dev/null | tail -n +2 | awk '{print $3}' \
           | grep -vE '^(com\.apple\.|application\.|0x|com\.valvesoftware\.|homebrew\.)'); do
  p="$LA/$l.plist"; [ -f "$p" ] || continue
  total=$((total+1))
  if /usr/bin/grep -q hc-wrap "$p"; then direct=$((direct+1)); continue; fi
  # every absolute path the plist names, followed one level into the file it points at
  hit=""
  for prog in $(/usr/bin/plutil -convert xml1 -o - "$p" 2>/dev/null \
                | /usr/bin/grep -oE '<string>/[^<]*</string>' \
                | sed 's:</\{0,1\}string>::g' | sort -u); do
    [ -f "$prog" ] || continue
    case "$(/usr/bin/file -b "$prog")" in *text*) ;; *) continue;; esac
    if /usr/bin/grep -q hc-wrap "$prog" 2>/dev/null; then hit="$prog"; break; fi
  done
  if [ -n "$hit" ]; then indirect=$((indirect+1)); echo "INDIRECT $l  (via $hit)"
  else bare=$((bare+1)); echo "BARE     $l"; fi
done
echo
echo "total=$total  direct=$direct  indirect=$indirect  bare=$bare"
