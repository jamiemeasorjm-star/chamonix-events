# WF Bulk-Ingest — Revert Runbook (2026-08-07)

Committed as `4bd8d1a`. The wf drop-in (wf_chamonix_com_detail.py) now bulk-ingests
chamonix.com event pages (namespaced ids, durable upsert) and is wired into
chamonix-refresh.sh step 2/5 as PRIMARY with the httpx chamonix_com_detail as
fallback. The live site was rebuilt and verified (135 events after dedup).

## Why this doc
Jamie must review the live site; if the bulk-ingested chamonix.com events look
wrong (bad titles, wrong dates, duplicates, clutter), roll back. Everything below
is reversible.

## One-command revert (full restore to pre-bulk-ingest state)
The DB was backed up BEFORE the bulk-ingest:

    cd /docker/hermes-agent-2bpx/data/chamonix-events/data
    # 1. stop writes
    supervisorctl -c /etc/supervisor/supervisord.conf stop chamonix-static
    # 2. restore the backup
    cp chamonix.db.bak-pre-bulkingest-202607  # (exact file below)
    cp chamonix.db.bak-pre-bulkingest-20260807-113913 chamonix.db
    # 3. also undo the code wiring so the next cron doesn't re-ingest

## Undo the refresh.sh wiring (back to httpx-only)
Replace the wf-first block in /root/.hermes/scripts/chamonix-refresh.sh (step
2/5) back to the simple httpx call:

    log "[2/5] P1: chamonix_com detail enrichment"
    if "$PY" -m scripts.chamonix_com_detail 2>&1 | tee -a "$LOG_FILE"; then
      log "[2/5] detail enrichment OK"
    else
      log "[2/5] detail enrichment failed; continuing"
    fi

## Restart after revert
    supervisorctl -c /etc/supervisor/supervisord.conf start chamonix-static
    # verify
    curl -s http://127.0.0.1:8090/healthz

## Minimal revert (keep new events, just stop re-ingesting)
If the events are fine but you don't want the cron running it, simply revert the
refresh.sh block above (do NOT restore the DB). Existing bulk rows stay; they'll
be deduped/tombstoned on the next httpx run.

## Backup file
- data/chamonix.db.bak-pre-bulkingest-20260807-113913
