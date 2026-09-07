#!/bin/zsh
# Build from a committed checkout so root-patch metadata identifies this fork.
set -eu
task_repo=${0:A:h}
cd "$task_repo"
if [[ -n "$(git status --porcelain)" ]]; then
    print -u2 'Commit or remove local changes before building an identifiable fork binary.'
    exit 1
fi
task_commit=$(git rev-parse HEAD)
task_date=$(git show -s --format=%cI HEAD)
task_branch=$(git symbolic-ref --quiet --short HEAD || print detached)
task_python=${OCLP_PYTHON:-python3}
exec "$task_python" Build-Project.command "$@" \
    --git-branch "$task_branch" \
    --git-commit-url "https://github.com/rctphone/OpenCore-Legacy-Patcher/commit/$task_commit" \
    --git-commit-date "$task_date"
