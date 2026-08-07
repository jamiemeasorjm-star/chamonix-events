#!/usr/bin/env bash
set -euo pipefail
# Runtime wrapper for the wf-based chamonix.com detail drop-in (migration slice 2).
#
# Runs scripts.wf_chamonix_com_detail under the web-foundation venv (where the
# wf / trafilatura / playwright deps live). Wired into the cron only AFTER the
# operator verifies the parity gate; it does not call any pipeline itself.
#
#   ./scripts/wf_chamonix_com_detail.sh [--dry-run] [--limit N] [--no-browser]
cd /docker/hermes-agent-2bpx/data/chamonix-events
export PYTHONPATH=/docker/hermes-agent-2bpx/data/chamonix-events
exec /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python -m scripts.wf_chamonix_com_detail "$@"
