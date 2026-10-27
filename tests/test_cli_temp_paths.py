"""CLI artifact defaults stay inside the checkout's task-local temp directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_cli_defaults_and_family_raw_paths_are_task_local(tmp_path):
    import cli

    args = cli._parse_args(["--family", "chatgpt"])
    assert Path(args.raw).parent.parent.parent == cli.ROOT / ".tmp"
    assert Path(args.raw).parent.name.startswith("20")
    assert Path(args.raw).name == "raw.json"
    assert Path(args.csv) == Path(args.raw).parent / "table.csv"
    assert Path(args.md) == Path(args.raw).parent / "table.md"
    replay = cli._parse_args(["--family", "chatgpt", "--skip-discover"])
    assert Path(replay.raw) == cli.ROOT / ".tmp" / "raw.json"

    custom_raw = tmp_path / "custom" / "raw.json"
    assert cli._family_raw_path(custom_raw, 1, "chatgpt") == custom_raw
    assert cli._family_raw_path(custom_raw, 2, "claude") == (
        tmp_path / "custom" / "raw.claude.json"
    )


def test_family_resource_split_keeps_global_limits_and_proxy_slices_disjoint(tmp_path, monkeypatch):
    import threading
    import time
    from argparse import Namespace
    from types import SimpleNamespace
    import cli

    active = 0
    peak = 0
    lock = threading.Lock()
    calls = []

    def fake_scan(family, args, raw_path):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append((family.name, args.http_workers, args.workers,
                          tuple(args.proxy_urls), tuple(args.discovery_proxy_urls)))
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"listings": []}

    monkeypatch.setattr(cli, "_run_one", fake_scan)
    proxies = [f"https://proxy-{i}.example:8085" for i in range(12)]
    args = Namespace(parallel_families=2, workers=2, http_workers=10,
                     proxy_urls=proxies, discovery_proxy_urls=proxies)
    families = [SimpleNamespace(name=name) for name in ("kimi", "claude", "zai")]
    result = cli._scan_families(families, args, tmp_path / "raw.json")

    assert set(result) == {"kimi", "claude", "zai"}
    assert peak == 2
    assert sorted((call[1], call[2]) for call in calls) == [(5, 1), (5, 1), (10, 2)]
    assert not (set(calls[0][3]) & set(calls[1][3]))
    assert not (set(calls[0][4]) & set(calls[1][4]))


def test_cli_ensures_nested_output_parent_directories(tmp_path):
    import cli

    paths = [tmp_path / "raw" / "raw.json", tmp_path / "reports" / "daily" / "table.csv"]
    cli._ensure_parent_dirs(*paths)

    assert paths[0].parent.is_dir()
    assert paths[1].parent.is_dir()
