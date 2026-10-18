#!/usr/bin/env bash
# Search the worktree and git history for identifiers that must not ship.
# Patterns are concatenated so this file itself does not contain them.
set -u
cd "$(dirname "$0")/.."

needles=(
  "example-term-3"
  "example-term-1"
  "example-term-4"
  "example-term-5"
  "example-term-6"
  "example-term-7"
  "example-term-2"
  "example-term-8"
  "example-term-9"
)

echo "== worktree (git grep, tracked files) =="
worktree=0
for needle in "${needles[@]}"; do
  if git grep -n -i -I -e "$needle" -- . ':(exclude)scripts/scan-history.sh' ':(exclude)tests/test_privacy.py'; then
    worktree=1
  fi
done
if [[ "$worktree" -eq 0 ]]; then
  echo "no matches in tracked file contents"
fi

echo
echo "== commit messages =="
messages=0
while IFS= read -r needle; do
  if git log --all --format='%H %s' | grep -i -n -e "$needle"; then
    messages=1
  fi
done < <(printf '%s\n' "${needles[@]}")
if [[ "$messages" -eq 0 ]]; then
  echo "no matches in commit subjects"
fi

echo
echo "== full history patches, excluding author headers =="
# Author/Commit lines are reported separately so a repository's existing
# identity is not mixed up with source that this tree introduced.
history=0
patch="$(git log --all -p --format='COMMIT %H%nSUBJECT %s' )"
for needle in "${needles[@]}"; do
  if printf '%s\n' "$patch" | grep -i -n -e "$needle"; then
    history=1
  fi
done
if [[ "$history" -eq 0 ]]; then
  echo "no matches in commit subjects or patches"
fi

echo
echo "== author headers (informational) =="
git log --all --format='%H%n%an <%ae>' | grep -i -n -e "example-term-3" || echo "no author header matches"
