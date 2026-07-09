#!/bin/sh
# One-shot CI entrypoint: run the heaven review agent once against /repo, then exit.
# (NOT a server — unlike the observatory container. A GitHub Actions job runs this and ends.)
set -eu

: "${MODE:?set MODE=review|pr|harvest}"
: "${MINIMAX_API_KEY:?set MINIMAX_API_KEY (the model credential)}"

export HEAVEN_DATA_DIR="${HEAVEN_DATA_DIR:-/tmp/heaven_data}"
mkdir -p "$HEAVEN_DATA_DIR"

# gh reads GH_TOKEN, else GITHUB_TOKEN (Actions provides GITHUB_TOKEN automatically)
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

# The Actions checkout at /repo is owned by a different uid than this container's user;
# without this, every `git -C /repo ...` fails with "dubious ownership".
git config --global --add safe.directory '*' || true

# CWD MUST be the AIOS so resolve_devdirs loads /cicd_aios/.claude rules+skills into the
# agent's system prompt. The agent operates on /repo via `git -C /repo`, never by cd-ing here.
cd /cicd_aios
exec python3 ci_agent.py
