#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
LOG_DIR="/opt/data/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

echo "[$TIMESTAMP] === Chamonix scraper run starting ==="

run() {
    local name="$1"
    shift
    echo "[$TIMESTAMP] Running $name..."
    if /usr/bin/python3 -m "$@" >> "$LOG_DIR/chamonix-scraper.log" 2>&1; then
        echo "[$TIMESTAMP] $name OK"
    else
        echo "[$TIMESTAMP] $name FAILED (exit $?)"
    fi
}

run "chamonix_net" scripts.chamonix_net --no-detail
run "allocine_vox" scripts.allocine_vox
run "chamonix_com" scripts.chamonix_com
run "chamonix_com_detail" scripts.chamonix_com_detail

# Cleanup: remove past events
echo "[$TIMESTAMP] Removing past events..."
/usr/bin/python3 scripts/clean_past.py
echo "[$TIMESTAMP] === Chamonix scraper run complete ==="
