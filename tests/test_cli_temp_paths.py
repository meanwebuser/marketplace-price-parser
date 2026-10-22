"""CLI artifact defaults stay inside the checkout's task-local temp directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_cli_defaults_and_family_raw_paths_are_task_local(tmp_path):
    import cli

    args = cli._parse_args(["--family", "chatgpt"])
    assert Path(args.raw) == cli.ROOT / ".tmp" / "raw.json"
    assert Path(args.csv) == cli.ROOT / ".tmp" / "table.csv"
    assert Path(args.md) == cli.ROOT / ".tmp" / "table.md"

    custom_raw = tmp_path / "custom" / "raw.json"
    assert cli._family_raw_path(custom_raw, 1, "chatgpt") == custom_raw
    assert cli._family_raw_path(custom_raw, 2, "claude") == (
        cli.ROOT / ".tmp" / "claude_raw.json"
    )


def test_cli_ensures_nested_output_parent_directories(tmp_path):
    import cli

    paths = [tmp_path / "raw" / "raw.json", tmp_path / "reports" / "daily" / "table.csv"]
    cli._ensure_parent_dirs(*paths)

    assert paths[0].parent.is_dir()
    assert paths[1].parent.is_dir()
