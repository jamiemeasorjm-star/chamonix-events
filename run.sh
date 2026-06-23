#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=============================================="
echo "  Chamonix Events — Daily Refresh Pipeline"
echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=============================================="

# Step 1: Scrape Le Vox cinema schedule from PDF
echo ""
echo "[1/2] Le Vox PDF scraper..."
python3 scripts/vox_pdf.py 2>&1
CINEMA_EXIT=$?
if [ $CINEMA_EXIT -ne 0 ]; then
    echo "WARNING: Cinema scraper failed (exit $CINEMA_EXIT). Continuing..."
fi

# Step 2: Build HTML from merged data
echo ""
echo "[2/2] Build index.html..."
python3 build.py 2>&1
BUILD_EXIT=$?
if [ $BUILD_EXIT -ne 0 ]; then
    echo "ERROR: Build failed (exit $BUILD_EXIT)"
    exit 1
fi

echo ""
echo "=============================================="
echo "  Done — Site refreshed at $(date)"
echo "=============================================="
