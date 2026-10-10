#!/usr/bin/env bash
# prepare-workspace.sh <repo> <commit>
# Puts the tree of <commit> in /work as a fresh one-commit repository and installs its dependencies
# (from the uv cache only when UV_OFFLINE is set, as it is in the final image).
# The workspace carries no history after <commit>, so the original fix cannot be read from git.
set -euo pipefail
repo="$1"
commit="$2"
find /work -mindepth 1 -delete
git -C "/opt/src/$repo" archive "$commit" | tar -x -C /work
cd /work
git init -q -b main
git add -A
git -c user.name=trial -c user.email=trial@localhost commit -q -m "start of task"
uv sync --frozen --quiet
