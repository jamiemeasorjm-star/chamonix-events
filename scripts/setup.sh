#!/usr/bin/env bash
# Chamonix Events — Reproducible Deploy Script (T40)
#
# Usage:
#   bash scripts/setup.sh              # fresh install
#   bash scripts/setup.sh --upgrade    # upgrade venv deps only
#   bash scripts/setup.sh --pipeline   # run the data pipeline
#   bash scripts/setup.sh --server     # start the HTTP server
#
# Idempotent: safe to re-run any number of times.
#
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

# ---- config ----
PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-venv}"
PORT="${CHAMONIX_PORT:-8090}"
LOG_DIR="${LOG_DIR:-/opt/data/logs}"

# ---- colors ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
ok()  { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn(){ printf "${YELLOW}⚠${NC} %s\n" "$1"; }
fail(){ printf "${RED}✗${NC} %s\n" "$1"; exit 1; }

# ---- step 1: check python ----
step_check() {
  echo ""
  echo "--- Step 1/6: Checking Python ---"
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    fail "Python not found: $PYTHON. Install python3.11+ and try again."
  fi
  ver=$("$PYTHON" --version 2>&1)
  ok "Found $ver"
}

# ---- step 2: create venv + install deps ----
step_venv() {
  echo ""
  echo "--- Step 2/6: Virtual environment ---"
  if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Created venv at $VENV_DIR"
  else
    ok "Venv already exists at $VENV_DIR"
  fi

  PIP="$VENV_DIR/bin/pip3"
  if [ ! -x "$PIP" ]; then
    PIP="$VENV_DIR/bin/pip"
  fi

  # Upgrade pip + install deps
  "$PIP" install --quiet --upgrade pip
  ok "pip upgraded"

  if [ -f requirements.txt ] && [ -s requirements.txt ]; then
    "$PIP" install --quiet -r requirements.txt
  else
    # Minimal deps if requirements.txt is empty/missing
    "$PIP" install --quiet httpx beautifulsoup4 lxml PyMuPDF PyYAML
  fi
  ok "Dependencies installed"

  # Add a note in requirements.txt for future reference
  if [ ! -f requirements.txt ] || [ ! -s requirements.txt ]; then
    cat > requirements.txt <<EOF
# Chamonix Events — Python dependencies
httpx>=0.27
beautifulsoup4>=4.12
lxml>=5.0
PyMuPDF>=1.23
PyYAML>=6.0
EOF
    ok "Created requirements.txt"
  fi
}

# ---- step 3: verify sources.yaml ----
step_config() {
  echo ""
  echo "--- Step 3/6: Configuration ---"
  if [ -f sources.yaml ]; then
    ok "sources.yaml found"
    "$VENV_DIR/bin/python3" -c "
import yaml
with open('sources.yaml') as f:
    data = yaml.safe_load(f)
print(f'  Global threshold: {data.get(\"min_publish_confidence\", \"not set\")}')
print(f'  Sources defined: {len(data.get(\"sources\", []))}')
" 2>&1 || warn "Could not parse sources.yaml"
  else
    warn "sources.yaml not found — run from project root"
  fi
}

# ---- step 4: run data pipeline ----
step_pipeline() {
  echo ""
  echo "--- Step 4/6: Data Pipeline ---"
  PY="$VENV_DIR/bin/python3"

  run_ok() {
    local label="$1"; shift
    if "$PY" "$@" 2>&1; then
      ok "$label"
      return 0
    else
      warn "$label failed (non-fatal)"
      return 1
    fi
  }

  run_ok "chamonix_net" -m scripts.chamonix_net --no-detail || true
  run_ok "chamonix_com" -m scripts.chamonix_com || true

  # Check if DB has data; if not, run the scraper again
  HAS_DATA=$("$PY" -c "
from scripts.storage import get_storage
s = get_storage()
n = s.conn.execute('SELECT count(*) FROM events').fetchone()[0]
print(n)
" 2>/dev/null || echo "0")

  if [ "$HAS_DATA" = "0" ] || [ "$HAS_DATA" = "" ]; then
    warn "No events found after scraping (first run may need multiple passes)"
  else
    ok "Events in DB: $HAS_DATA"
  fi

  run_ok "clean_past" scripts/clean_past.py || true
  run_ok "vox_pdf" scripts/vox_pdf.py || true
}

# ---- step 5: build static site ----
step_build() {
  echo ""
  echo "--- Step 5/6: Build ---"
  PY="$VENV_DIR/bin/python3"

  if "$PY" build.py 2>&1; then
    ok "Build complete"
    # Show result
    "$PY" -c "
import json
with open('data/last_build.json') as f:
    b = json.load(f)
print(f'  Events: {b.get(\"events\",\"?\")}')
print(f'  Cinema: {b.get(\"cinema\",\"?\")}')
"
  else
    fail "Build failed"
  fi
}

# ---- step 6: configure server ----
step_server() {
  echo ""
  echo "--- Step 6/6: Server ---"
  PY="$VENV_DIR/bin/python3"

  # Check if already running
  if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    warn "Port $PORT already in use (server may already be running)"
    return 0
  fi

  # Try supervisor (production) or nohup (dev)
  if command -v supervisorctl >/dev/null 2>&1; then
    if supervisorctl status chamonix-events >/dev/null 2>&1; then
      ok "Supervisor already configured for chamonix-events"
      supervisorctl start chamonix-events 2>/dev/null || true
    else
      warn "Supervisor not configured for chamonix-events — add this to supervisor config:"
      echo "  [program:chamonix-events]"
      echo "  command=$PY -m scripts.http_server"
      echo "  directory=$DIR"
      echo "  user=root"
      echo "  autostart=true"
      echo "  autorestart=true"
    fi
  else
    warn "No supervisor found. Start the server manually:"
    echo "  $PY -m scripts.http_server &"
  fi
}

# ---- main ----
main() {
  echo "================================================"
  echo "  Chamonix Events — Setup (T40)"
  echo "  Project: $DIR"
  echo "================================================"

  if [ "${1:-}" = "--upgrade" ]; then
    step_venv
    ok "Upgrade complete"
    exit 0
  fi

  if [ "${1:-}" = "--pipeline" ]; then
    step_pipeline
    step_build
    exit 0
  fi

  if [ "${1:-}" = "--server" ]; then
    step_server
    exit 0
  fi

  # Full setup
  step_check
  step_venv
  step_config
  step_pipeline
  step_build
  step_server

  echo ""
  echo "================================================"
  echo "  Setup complete!"
  echo "  Site: http://localhost:$PORT/"
  echo "  Dashboard: http://localhost:$PORT/admin/"
  echo "  Health: http://localhost:$PORT/healthz"
  echo "================================================"
}

main "$@"