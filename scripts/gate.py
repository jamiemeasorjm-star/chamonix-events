#!/usr/bin/env python3
"""Governance gate (T33): inspect staged changes and emit R1/R2/R3 label.

Usage:
    python3 scripts/gate.py          # checks git diff HEAD
    python3 scripts/gate.py --diff   # read diff from stdin (for pre-commit hook)

Exit codes:
    0 = R1 (safe) — changes are docs-only or template copies
    1 = R2 (review) — changes touch storage/models/sources/pipeline
    2 = error / no diff
"""

import re
import subprocess
import sys
from pathlib import Path


# R2 paths: changes here require human review before deploy.
R2_PATHS = [
    "scripts/storage.py",
    "scripts/models.py",
    "sources.yaml",
    "build.py",
    "scripts/http_server.py",
    "scripts/submit",
    "scripts/pipeline",
    "scripts/dedup.py",
    "scripts/scoring.py",
    "scripts/translate_job.py",
]

# R1 paths: safe, doc-only or template copy
R1_PATHS = [
    "docs/",
    "README.md",
    "*.template",
    ".github/",
]


def get_diff() -> str:
    """Get the diff of staged+unstaged changes from git HEAD."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            capture_output=True, text=True, timeout=10,
            cwd=Path(__file__).resolve().parent.parent,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def classify(diff_text: str) -> tuple[str, list[str]]:
    """Return (risk_level, touched_paths)."""
    touched = set()
    for line in diff_text.splitlines():
        # git diff --stat lines look like: " scripts/storage.py | 15 ++++++++---"
        m = re.match(r"^\s+(.+?)\s+\|", line)
        if m:
            fpath = m.group(1).strip()
            touched.add(fpath)

    if not touched:
        return "R0", []

    # Check for R2 paths
    for f in touched:
        for r2 in R2_PATHS:
            if r2.endswith("/"):
                if f.startswith(r2):
                    return "R2", sorted(touched)
            elif r2.endswith("*"):
                if f.endswith(r2.replace("*", "")):
                    return "R2", sorted(touched)
            elif f == r2 or f.startswith(r2):
                return "R2", sorted(touched)

    # Check if all files are R1
    all_r1 = True
    for f in touched:
        is_r1 = False
        for r1 in R1_PATHS:
            if r1.endswith("/"):
                if f.startswith(r1):
                    is_r1 = True
                    break
            elif r1.endswith("*"):
                if f.endswith(r1.replace("*", "")):
                    is_r1 = True
                    break
            elif f == r1:
                is_r1 = True
                break
        if not is_r1:
            all_r1 = False
            break

    if all_r1:
        return "R1", sorted(touched)

    return "R2", sorted(touched)


def main() -> int:
    diff = get_diff()
    if not diff:
        print("[gate] R0 — no changes detected or not a git repository")
        return 2

    level, files = classify(diff)

    print(f"[gate] Risk level: {level}")
    print(f"[gate] Files touched ({len(files)}):")
    for f in files:
        print(f"       {f}")

    if level == "R2":
        print()
        print("[gate] ⚠  R2 — changes require human review.")
        print("[gate]    Paths: scripts/storage.py, models.py, sources.yaml, build.py,")
        print("[gate]           http_server.py, submit/*, pipeline/*, dedup.py, scoring.py")
        print()
        print("[gate] Commit blocked by T33 governance gate.")
        print("[gate] To bypass: GATE_BYPASS=1 git commit")
        bypass = "GATE_BYPASS" in os.environ
        if bypass:
            print("[gate] GATE_BYPASS set — allowing commit.")
            return 0
        return 1

    if level == "R1":
        print("[gate] ✅ R1 — safe change (docs or templates).")
        return 0

    print(f"[gate] ✅ {level} — no governance concern.")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())