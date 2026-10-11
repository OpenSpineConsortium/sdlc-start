#!/usr/bin/env bash
# Answer an adoption request that ends without a pull request: post the
# reason on its issue, close the issue as not planned, and tell the later
# steps of .github/workflows/adopt.yml and adopt-run.yml to do nothing,
# through REFUSED in $GITHUB_ENV. A refusal is the workflow doing its job, so the step that
# calls this ends green unless it exits 1 on purpose, as the one for a
# broken App does so that the owner sees a red run; nothing else turns the
# run red but a real failure. With --keep-open the issue stays open, for a
# refusal that is the owner's to fix, after which the run can be started
# again.
#
# The message is the workflow's own text, never the issue's: it may name
# the repository only after scripts/adopt.py parse has checked the name.
# Needs ISSUE_TOKEN (the workflow's GITHUB_TOKEN, which may write this
# repository's issues), ISSUE (the issue's number) and GITHUB_REPOSITORY.
# On the sweep's path there is no issue: ISSUE is empty, nothing is
# posted here, and the message is kept in $RUNNER_TEMP/refusal for the
# step of adopt-run.yml that tells the repository.
#
# Usage: bash scripts/refuse.sh [--keep-open] MESSAGE
set -eu

keep_open=false
if [ "${1:-}" = "--keep-open" ]; then
  keep_open=true
  shift
fi
message="${1:?usage: refuse.sh [--keep-open] MESSAGE}"

if [ -n "${ISSUE:-}" ]; then
  GH_TOKEN="$ISSUE_TOKEN" gh issue comment "$ISSUE" --repo "$GITHUB_REPOSITORY" --body "$message"
  if [ "$keep_open" = false ]; then
    GH_TOKEN="$ISSUE_TOKEN" gh issue close "$ISSUE" --repo "$GITHUB_REPOSITORY" --reason "not planned"
  fi
fi
echo "REFUSED=true" >> "$GITHUB_ENV"
if [ -n "${RUNNER_TEMP:-}" ]; then
  # The sentence about the front door's issue is for the front door's
  # issue; the repository's own issue, which quotes the file, has none.
  kept="${message%; this one is closed.}"
  kept="${kept%; this issue is closed.}"
  printf '%s\n' "$kept" > "$RUNNER_TEMP/refusal"
fi
echo "refused: $message"
