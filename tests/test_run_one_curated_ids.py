"""Regression tests for canonical GGSEL IDs at the discovery/collect boundary."""

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli


def test_run_one_collects_discovered_canonical_curated_ids_once(monkeypatch, tmp_path):
    canonical_ids = [str(10000 + index) for index in range(22)]
    curated_slugs = [f"claude-pro-month-{pid}" for pid in canonical_ids[-5:]]
    family = SimpleNamespace(name="claude", ggsel_ids=curated_slugs)
    candidates = [
        {"source": "ggsel", "native_id": pid, "url": f"https://ggsel.test/{pid}"}
        for pid in canonical_ids
    ]
    discovery = {
        "candidates": candidates,
        "plati_found": 0,
        "ggsel_found": 22,
        "transports": {"plati": "none", "ggsel": "playwright"},
        "errors": [],
    }
    monkeypatch.setattr(cli, "discover_all", lambda _family, _limit, **_kwargs: discovery)
    observed = {}

    def fake_collect(discovered_candidates, _out_path, **kwargs):
        observed["candidate_ids"] = [str(item["native_id"]) for item in discovered_candidates]
        observed["extra_ggsel_ids"] = kwargs.get("ggsel_ids") or []
        all_ids = observed["candidate_ids"] + list(observed["extra_ggsel_ids"])
        # Match collect()'s current string-based stable deduplication behavior.
        unique_ids = list(dict.fromkeys(all_ids))
        return {
            "listings": [{"marketplace": "ggsel", "pid": pid} for pid in unique_ids]
        }

    monkeypatch.setattr(cli, "collect", fake_collect)
    raw = cli._run_one(
        family,
        Namespace(skip_discover=False, max=80, max_pages=6, max_candidates=None,
                  allow_direct_discovery_fallback=False, workers=1, http_workers=4,
                  capture_retries=2, headless=True, parallel_families=1),
        tmp_path / "claude.raw.json",
    )

    assert observed["candidate_ids"] == canonical_ids
    assert observed["extra_ggsel_ids"] == []
    assert len(raw["listings"]) == discovery["ggsel_found"] == 22
