#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Load .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "========================================"
echo "  Chamonix Events - Scraper Pipeline"
echo "========================================"
echo ""

# Step 1: Scrape Facebook
echo "-- Step 1: Facebook Graph API Scraper --"
python3 scrapers/facebook_graph.py
FB_EXIT=$?
echo ""

# Exit gracefully if no pages enabled yet
if [ $FB_EXIT -ne 0 ]; then
    echo "Facebook scraper skipped or errored. Run again after adding page IDs."
    exit 0
fi

# Step 2: Normalize and merge
echo "-- Step 2: Normalize and Merge --"
python3 scrapers/normalize.py --latest
echo ""

echo "-- Done --"
