#!/usr/bin/env bash
# Push to GitHub. Requires the two setup steps in PUSH_SETUP.md first.
set -euo pipefail

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  echo "SSH auth to GitHub is not working yet."
  echo "See PUSH_SETUP.md — the public key still needs to be added at:"
  echo "  https://github.com/settings/ssh/new"
  exit 1
fi

branch=$(git rev-parse --abbrev-ref HEAD)
echo "pushing $branch -> origin"
git push -u origin "$branch"
echo "done: https://github.com/akshatsingh-dev/ClipMedia"
