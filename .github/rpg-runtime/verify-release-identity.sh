#!/usr/bin/env bash
set -euo pipefail

test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
git fetch --no-tags origin \
  '+refs/heads/retrom/f2efc98:refs/remotes/origin/retrom/f2efc98'
if [[ "$GITHUB_REF_TYPE" = tag ]]; then
  [[ "$GITHUB_REF_NAME" =~ ^retrom-core-f2efc98-r[1-9][0-9]*$ ]]
  test "$(git cat-file -t "refs/tags/$GITHUB_REF_NAME")" = tag
  test "$(git rev-list -n 1 "$GITHUB_REF_NAME")" = "$GITHUB_SHA"
  git merge-base --is-ancestor "$GITHUB_SHA" origin/retrom/f2efc98
else
  [[ "$GITHUB_REF_NAME" =~ ^(retrom|feat|fix|build)/[a-z0-9][a-z0-9/-]*$ ]]
  git merge-base --is-ancestor origin/retrom/f2efc98 "$GITHUB_SHA"
fi
git merge-base --is-ancestor \
  f585dc65499122a7abf503ca5d5dc8ef29452d91 "$GITHUB_SHA"
test -z "$(git rev-list --min-parents=2 \
  bf5f525e864b162bea0789d46932e5f800b80076.."$GITHUB_SHA")"
test "$(git rev-parse HEAD:mkxp-z)" = f2efc98a344c505a66820e06d6508092719b8dd2
test "$(git rev-parse HEAD:retroarch)" = 69a4f0ea1e8aaf442ae4858f2e7f2b31a1776576
