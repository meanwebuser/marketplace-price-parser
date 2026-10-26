"""Mock-only tests for permanent GGSEL category request failures."""

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from families.chatgpt import CONFIG as CHATGPT_CONFIG
from scanner import discover


def test_discover_all_keeps_curated_candidates_and_records_permanent_ggsel_failure(monkeypatch):
    class _Router:
        def default_handler(self, handler):
            self.handler = handler
            return handler

    class _FakeCrawler:
        def __init__(self, **_kwargs):
            self.router = _Router()
            self.failed_handler = None
            self.start_urls = []

        def failed_request_handler(self, handler):
            self.failed_handler = handler
            return handler

        async def run(self, start_urls):
            self.start_urls = list(start_urls)
            failed_context = SimpleNamespace(
                request=SimpleNamespace(url=self.start_urls[0])
            )
            await self.failed_handler(failed_context, RuntimeError("HTTP 404 Not Found"))

    crawlee = ModuleType("crawlee")
    crawlers = ModuleType("crawlee.crawlers")
    crawlers.PlaywrightCrawler = _FakeCrawler
    crawlee.crawlers = crawlers
    monkeypatch.setitem(sys.modules, "crawlee", crawlee)
    monkeypatch.setitem(sys.modules, "crawlee.crawlers", crawlers)

    family = replace(
        CHATGPT_CONFIG,
        ggssel_category="kimi",
        ggsel_ids=["kimi-pro-1-month-curated-102635272"],
    )
    monkeypatch.setattr(
        discover,
        "discover_plati",
        lambda _family, _max_results, query_errors=None, proxy_urls=(), coverage=None: (
            coverage.update(status="ok", pagesFetched=1, queries=[]) or
            ([{"source": "plati", "native_id": "5001", "label": "Kimi Pro 1 месяц"}], "urllib")
        ),
    )

    result = discover.discover_all(family)

    assert result["ggsel_found"] == 1
    assert result["candidates"][-1]["native_id"] == "102635272"
    assert result["transports"]["ggsel"] == "playwright-partial"
    assert len(result["transports"]["ggselRequestFailures"]) == 1
    failure = result["transports"]["ggselRequestFailures"][0]
    assert "https://ggsel.net/catalog/kimi" in failure
    assert "HTTP 404 Not Found" in failure
    assert failure in result["errors"]
