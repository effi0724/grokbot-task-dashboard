#!/usr/bin/env bash
# Search the worktree and git history for identifiers that must not ship.
set -u
cd "$(dirname "$0")/.."

# The term list is never committed. Put one term per line in .privacy-terms
# (gitignored; lines starting with # are ignored), or set PRIVACY_TERMS to a
# comma-separated list. See .privacy-terms.example.
needles=()
if [[ -n "${PRIVACY_TERMS:-}" ]]; then
  IFS=',' read -r -a needles <<<"$PRIVACY_TERMS"
elif [[ -f .privacy-terms ]]; then
  while IFS= read -r line; do
    line="${line%%#*}"; line="$(echo "$line" | xargs)"
    [[ -n "$line" ]] && needles+=("$line")
  done < .privacy-terms
fi
if [[ "${#needles[@]}" -eq 0 ]]; then
  echo "no privacy terms configured: create .privacy-terms or set PRIVACY_TERMS" >&2
  exit 2
fi

echo "== worktree (git grep, tracked files) =="
worktree=0
for needle in "${needles[@]}"; do
  if git grep -n -i -I -e "$needle" -- .; then
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
headers="$(git log --all --format='%H %an <%ae> %cn <%ce>')"
author_hit=0
for needle in "${needles[@]}"; do
  if printf '%s\n' "$headers" | grep -i -n -e "$needle"; then author_hit=1; fi
done
[[ "$author_hit" -eq 0 ]] && echo "no author/committer header matches"
