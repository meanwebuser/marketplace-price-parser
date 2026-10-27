import json
import subprocess

from scanner import ggsel_ssr
from scanner.collect import collect


def test_collect_uses_http_fast_path_without_starting_chromium(tmp_path, monkeypatch):
    output = tmp_path / "raw.json"
    candidate = {"source": "ggsel", "native_id": "123", "url": "https://ggsel.net/catalog/product/123"}

    async def fake_collect(candidates, *, workers, proxy_urls):
        assert workers == 10
        assert candidates == [candidate]
        return [{"marketplace": "ggsel", "pid": "123", "options": []}], [], {
            "impit": 1, "curl_cffi": 0, "browser_fallback": 0,
        }

    monkeypatch.setattr(ggsel_ssr, "collect_ggsel_ssr", fake_collect)
    monkeypatch.setattr("scanner.collect.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("browser should not start")))

    raw = collect([candidate], output, workers=2, http_workers=10, headless=True)

    assert raw["listings"][0]["pid"] == "123"
    assert raw["config"]["httpWorkers"] == 10
    assert raw["config"]["browserWorkers"] == 2
    assert raw["config"]["transportCounts"]["impit"] == 1
    assert json.loads(output.read_text())["listings"][0]["marketplace"] == "ggsel"


def test_collect_sends_only_unsupported_http_listings_to_playwright(tmp_path, monkeypatch):
    output = tmp_path / "raw.json"
    candidates = [
        {"source": "plati", "native_id": "1", "url": "https://plati.market/itm/1"},
        {"source": "ggsel", "native_id": "2", "url": "https://ggsel.net/catalog/product/2"},
        {"source": "ggsel", "native_id": "3", "url": "https://ggsel.net/catalog/product/3"},
    ]

    async def fake_collect(items, *, workers, proxy_urls):
        assert workers == 10
        return [{"marketplace": "ggsel", "pid": "2", "options": []}], [candidates[2]], {
            "impit": 1, "curl_cffi": 0, "browser_fallback": 1,
        }

    def fake_browser(command, **kwargs):
        assert command[command.index("--plati-pids") + 1] == "1"
        assert command[command.index("--ggsel-ids") + 1] == "3"
        output.write_text(json.dumps({"config": {"workers": 2}, "listings": [
            {"marketplace": "plati", "pid": "1"}, {"marketplace": "ggsel", "pid": "3"},
        ]}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ggsel_ssr, "collect_ggsel_ssr", fake_collect)
    monkeypatch.setattr("scanner.collect.subprocess.run", fake_browser)

    raw = collect(candidates, output, workers=2, http_workers=10, headless=True)

    assert [(item["marketplace"], item["pid"]) for item in raw["listings"]] == [
        ("ggsel", "2"), ("plati", "1"), ("ggsel", "3"),
    ]
    assert raw["config"]["transportCounts"] == {"impit": 1, "curl_cffi": 0, "browser_fallback": 1}
