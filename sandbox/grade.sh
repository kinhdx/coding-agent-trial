#!/usr/bin/env bash
# grade.sh <repo> <commit> <test-file>
# Runs in a fresh container with no network. Applies /trial/patch.diff to <commit>, restores the test suite
# of <commit> (tests the agent added or changed are not used for grading), appends /trial/hidden_code.py to
# <test-file> as tests/test_hidden_task.py, then runs the hidden tests and the original suite.
set -uo pipefail
repo="$1"
commit="$2"
test_file="$3"
prepare-workspace.sh "$repo" "$commit"
cd /work
applied=true
if [ -s /trial/patch.diff ]; then
  git apply --whitespace=nowarn /trial/patch.diff 2> /trial/apply.log || applied=false
fi
git checkout -q HEAD -- tests
git clean -fdq tests
{ cat "$test_file"; printf '\n\n'; cat /trial/hidden_code.py; } > tests/test_hidden_task.py
uv run --offline --frozen pytest -q -p no:cacheprovider tests/test_hidden_task.py -k hidden \
  --junitxml=/trial/hidden.xml > /trial/hidden.log 2>&1
hidden=$?
uv run --offline --frozen pytest -q -p no:cacheprovider tests --ignore=tests/test_hidden_task.py \
  --junitxml=/trial/suite.xml > /trial/suite.log 2>&1
suite=$?
printf '{"applied": %s, "hidden_exit": %d, "suite_exit": %d}\n' "$applied" "$hidden" "$suite" > /trial/grade.json
