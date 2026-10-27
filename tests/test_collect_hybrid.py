import json
import subprocess
import io
from types import SimpleNamespace

from scanner import ggsel_ssr, plati_http
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
        assert workers == 7
        return [{"marketplace": "ggsel", "pid": "2", "options": []}], [candidates[2]], {
            "impit": 1, "curl_cffi": 0, "browser_fallback": 1,
        }

    async def fake_plati(items, *, workers, proxy_urls):
        assert workers == 3
        assert items == [candidates[0]]
        assert set(proxy_urls).isdisjoint(set([
            "http://proxy-2.example:8085", "http://proxy-4.example:8085",
        ]))
        return [], [candidates[0]], {"pageRequests": 1, "optionRequests": 0,
                                      "priceOptions": 0, "failedOptions": 0}

    def fake_browser(command, **kwargs):
        assert command[command.index("--plati-pids") + 1] == "1"
        assert command[command.index("--ggsel-ids") + 1] == "3"
        output.write_text(json.dumps({"config": {"workers": 2}, "listings": [
            {"marketplace": "plati", "pid": "1"}, {"marketplace": "ggsel", "pid": "3"},
        ]}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=io.StringIO(""), wait=lambda: 0)

    monkeypatch.setattr(ggsel_ssr, "collect_ggsel_ssr", fake_collect)
    monkeypatch.setattr(plati_http, "collect_plati_http", fake_plati)
    monkeypatch.setattr("scanner.collect.subprocess.Popen", fake_browser)

    raw = collect(candidates, output, workers=2, http_workers=10, headless=True,
                  proxy_urls=[f"http://proxy-{i}.example:8085" for i in range(1, 5)])

    assert [(item["marketplace"], item["pid"]) for item in raw["listings"]] == [
        ("ggsel", "2"), ("plati", "1"), ("ggsel", "3"),
    ]
    assert raw["config"]["transportCounts"] == {
        "plati_http": 0,
        "impit": 1,
        "curl_cffi": 0,
        "plati_browser_fallback": 1,
        "browser_fallback": 1,
        "plati_pageRequests": 1,
        "plati_optionRequests": 0,
        "plati_priceOptions": 0,
        "plati_failedOptions": 0,
    }
    assert set(raw["config"]["transportDurationsMs"]) == {"platiHttp", "ggselSsr", "browserFallback"}
