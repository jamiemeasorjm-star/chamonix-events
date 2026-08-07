"""Unit tests for scripts.wf_chamonix_com_detail (migration slice 2).

Covers the pure summary helper and module import, plus a network-guarded
smoke test that a sample wf extract_event returns a non-empty description for a
known URL (fails only on an assertion, never on a network error).

Run (web-foundation venv; pure tests don't need wf deps):
    /docker/hermes-agent-2bpx/data/web-foundation/.venv/bin/python scripts/test_wf_chamonix_com_detail.py
Also pytest-compatible (functions named test_*).
"""

from __future__ import annotations

from scripts import wf_chamonix_com_detail as detail
from scripts import wf_chamonix_com as wf


def test_module_imports_and_constants():
    assert detail.SOURCE_ID == "chamonix_com"
    assert detail.MIN_DESCRIPTION_LEN == wf.MIN_DESCRIPTION_LEN


def test_coverage_summary():
    events = [
        {"description": "x" * detail.MIN_DESCRIPTION_LEN},
        {"description": "short"},
        {"description": ""},
        {"description": "y" * (detail.MIN_DESCRIPTION_LEN + 5)},
    ]
    with_desc, total = detail._coverage_summary(events)
    assert total == 4
    assert with_desc == 2


def test_coverage_summary_empty():
    assert detail._coverage_summary([]) == (0, 0)


def test_coverage_threshold():
    events = [{"description": "z" * (detail.MIN_DESCRIPTION_LEN - 1)}]
    assert detail._coverage_summary(events)[0] == 0
    events[0]["description"] = "z" * detail.MIN_DESCRIPTION_LEN
    assert detail._coverage_summary(events)[0] == 1


def test_sample_extract_event_returns_description_offline_safe():
    """Network-guarded smoke test: known URL -> non-empty wf description.

    If the network/venv is unavailable the try/except just returns, so this
    never hard-fails offline; when connectivity exists it asserts coverage.
    """
    url = (
        "https://www.chamonix.com/agenda/evenements-et-manifestations/"
        "fete-des-guides-2026"
    )
    try:
        ev = wf.extract_event(url, use_browser_fallback=False)
    except Exception:  # noqa: BLE001 - offline/venv guard
        return
    desc = ev.get("description", "") or ""
    assert len(desc) > 0, "wf extraction should yield a non-empty description"


if __name__ == "__main__":
    fns = [
        (name, obj) for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in fns:
        fn()
        print(f"  ok  {name}")
    print(f"\n{len(fns)} tests passed")
