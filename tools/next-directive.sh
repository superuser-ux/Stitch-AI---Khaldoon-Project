#!/usr/bin/env bash
# Fetch the next human-approved directive for Claude Code to execute.
# Usage: tools/next-directive.sh            # print the oldest directive:approved issue (number, title, url, body)
#        tools/next-directive.sh --list     # list all open directive issues by state
set -euo pipefail
REPO="Kholio/tanaghom"

if [[ "${1:-}" == "--list" ]]; then
  gh issue list --repo "$REPO" --state open --label directive:pending  --json number,title --jq '.[] | "  pending   #\(.number) \(.title)"' || true
  gh issue list --repo "$REPO" --state open --label directive:approved --json number,title --jq '.[] | "  approved  #\(.number) \(.title)"' || true
  gh issue list --repo "$REPO" --state open --label directive:running  --json number,title --jq '.[] | "  running   #\(.number) \(.title)"' || true
  exit 0
fi

num=$(gh issue list --repo "$REPO" --state open --label directive:approved \
        --json number,createdAt --jq 'sort_by(.createdAt) | .[0].number // empty')

if [[ -z "$num" ]]; then
  echo "No approved directive pending. (Apply the 'directive:approved' label to queue one.)"
  exit 0
fi

gh issue view "$num" --repo "$REPO" --json number,title,url,body \
  --jq '"═══ DIRECTIVE #\(.number) ═══\n\(.title)\n\(.url)\n\n\(.body)"'
