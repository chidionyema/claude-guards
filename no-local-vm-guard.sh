#!/bin/sh
# R26-no-local-vm-on-laptop (founder 2026-08-25): no VM boots on the Mac; compute is Oracle.
# Exit 1 with the evidence when a VM process or a VM LaunchAgent exists. Exit 0 with a receipt otherwise.
# Self-test: NO_LOCAL_VM_FAKE_PROC=1 must fail, NO_LOCAL_VM_FAKE_PROC= must pass on a clean box.
LA="${HOME}/Library/LaunchAgents"
procs=$(ps -Ao pid,comm | grep -E '(/|^ *[0-9]+ +)(colima|limactl|qemu-system[^ ]*|vfkit)$' )
[ -n "${NO_LOCAL_VM_FAKE_PROC:-}" ] && procs="FAKE 0 colima start (self-test)"
plists=$(ls "$LA" 2>/dev/null | grep -iE 'colima|lima|k3d|docker' )
if [ -n "$procs" ] || [ -n "$plists" ]; then
  echo "no-local-vm-guard: FAIL (R26). VM process or LaunchAgent present on the laptop:"
  [ -n "$procs" ] && echo "$procs"
  [ -n "$plists" ] && echo "LaunchAgents: $plists"
  echo "fix: launchctl bootout gui/$(id -u)/homebrew.mxcl.colima; mv $LA/homebrew.mxcl.colima.plist ~/.claude/state/disabled-launchagents/; pkill -f 'colima|limactl'"
  exit 1
fi
echo "no-local-vm-guard: PASS (R26) no VM process, no VM LaunchAgent"
