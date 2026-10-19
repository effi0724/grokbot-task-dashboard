#!/usr/bin/env bash
# Run one stwatch watchdog pass and make sure the resident daemon is up.
# Call it from any scheduler you have (cron, launchd, a routine agent) every
# 15-30 minutes as a second layer behind `stwatch daemon`.
set -uo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
root="${ST_ROOT:-$HOME/.grokbot-task-dashboard}"
mkdir -p "$root/watchers"
exec 7>"$root/watchers/.watchdog-script.lock"
flock -w 30 7 || { echo "watchdog: previous pass still running; skipping"; exit 0; }
timeout -k 5 120 python3 "$here/cli/stwatch" watchdog
