#!/usr/bin/env bash
# Read Claude Code's /usage panel without sending a model request, save the
# text, and report it with `st claude --from-usage`. Requires tmux and a
# signed-in `claude` CLI.
#
#   CLAUDE_BIN=claude            path to the Claude Code CLI
#   CLAUDE_USAGE_DIR=$PWD        working directory for the session
#   CLAUDE_USAGE_OUT=$ST_ROOT/.claude-usage.txt
#   CLAUDE_USAGE_NO_PUSH=1       print only; do not run st
#   ST=st                        path to the st CLI
set -uo pipefail
root="${ST_ROOT:-$HOME/.grokbot-task-dashboard}"
bin="${CLAUDE_BIN:-claude}"
dir="${CLAUDE_USAGE_DIR:-$PWD}"
out="${CLAUDE_USAGE_OUT:-$root/.claude-usage.txt}"
session="st-claude-usage-$$"
command -v tmux >/dev/null || { echo "tmux is required" >&2; exit 2; }
mkdir -p "$(dirname "$out")"
tmux new-session -d -s "$session" -x 200 -y 60 -c "$dir" "$bin; sleep 30"
sleep 10
tmux send-keys -t "$session" '/usage'; sleep 2; tmux send-keys -t "$session" Enter; sleep 8
tmux capture-pane -p -t "$session" -S -200 > "$out"
tmux kill-session -t "$session" 2>/dev/null
grep -A3 -E 'Current session|Current week' "$out" | grep -v '^\s*$' || { echo "no /usage data captured; is claude signed in?" >&2; exit 3; }
[ "${CLAUDE_USAGE_NO_PUSH:-0}" = 1 ] || "${ST:-st}" claude --from-usage "$out"
