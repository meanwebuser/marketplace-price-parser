"""Tests for family-specific marketplace candidate discovery."""

from pathlib import Path

from families.minimax import CONFIG as MINIMAX
from families.zai import CONFIG as ZAI
from scanner.discover import (
    GIFT_CARD_QUERIES,
    _extract_ggsel_gift_cards,
    _extract_ggsel_products,
    discover_gift_cards,
)


def test_ggsel_titleless_cards_fall_back_to_slug_and_filter_other_max_products():
    html = """
    <a href="/catalog/product/runway-ai-standard-pro-max-1-12m-102304393"></a>
    <a href="/catalog/product/minimax-token-plan-explore-1-month-102927393"></a>
    """

    offers = _extract_ggsel_products(html, MINIMAX)

    assert [offer["native_id"] for offer in offers] == ["102927393"]
    assert offers[0]["label"] == "minimax token plan explore 1 month"


def test_ggsel_numeric_cards_use_only_their_own_span_text_or_image_alt():
    html = """
    <a href="/catalog/product/102369748"></a>
    <a href="/catalog/product/102369748">
      <span>MiniMax M Plan Explore 1 Month</span>
    </a>
    <a href="/catalog/product/102438200">
      <img src="plan.webp" alt="MiniMax M Plan Build 1 Month">
    </a>
    <a href="/catalog/product/102000001"><span>Runway Max 1 Month</span></a>
    <span>MiniMax M Plan Explore 1 Month</span>
    <a href="/catalog/product/102000002"></a>
    <img src="outside.webp" alt="MiniMax M Plan Go 1 Month">
    <a href="/catalog/product/102000003"><img alt="Unrelated product"></a>
    <a href="/catalog/product/minimax-token-plan-max-1-month-102927393"></a>
    """

    offers = _extract_ggsel_products(html, MINIMAX)

    assert [offer["native_id"] for offer in offers] == ["102369748", "102438200", "102927393"]
    assert offers[0]["label"] == "MiniMax M Plan Explore 1 Month"
    assert offers[1]["label"] == "MiniMax M Plan Build 1 Month"


def test_saved_ggsel_overlay_links_use_sibling_metadata_from_the_same_card():
    html = (Path(__file__).parent / "fixtures" / "ggsel_zai_overlay_cards.html").read_text()

    offers = _extract_ggsel_products(html, ZAI)

    assert [offer["native_id"] for offer in offers] == ["102331610", "102109731"]
    assert offers[0]["label"] == "Подписка Z.ai MAX на 3 месяца –Z ai Премиум-подписка (ограниченное предложение)"
    assert offers[1]["label"] == "Апгрейд Z.AI Lite/Pro/Max: GLM 5.2, 1–12 месяца | F.A.S.T, FULL WARRANTY"
    # Numeric-only URLs use exactly the same card metadata, while retaining
    # the original fixture as evidence for the actual slug-ID regression.
    numeric = html.replace(
        "/catalog/product/podpiska-z-ai-max-na-3-mesiaca-z-ai-premium-podpiska-ogranicennoe-predlozenie-102331610",
        "/catalog/product/102331610",
    )
    assert [offer["native_id"] for offer in _extract_ggsel_products(numeric, ZAI)] == ["102331610", "102109731"]


def test_card_metadata_does_not_promote_topup_or_leak_between_product_ids():
    html = """
    <div data-testid="card">
      <a href="/catalog/product/zai-max-subscription-1-month-9001"></a>
      <img alt="Пополнение баланса Z.ai API">
    </div>
    <div data-testid="card">
      <a href="/catalog/product/9002">Z.ai MAX subscription 3 месяца</a>
      <a href="/catalog/product/9003"></a>
    </div>
    <div data-testid="card"><a href="/catalog/product/9004"></a></div>
    <div>Z.ai MAX subscription 3 месяца</div>
    """

    assert [offer["native_id"] for offer in _extract_ggsel_products(html, ZAI)] == ["9002"]


def test_gift_card_search_has_query_variants_and_does_not_collect_turkey_yet():
    tr = discover_gift_cards("TR")

    assert len(GIFT_CARD_QUERIES["US"]) >= 3
    assert any("Apple Gift Card" in query and "USA" in query for query in GIFT_CARD_QUERIES["US"])
    assert any("iTunes Gift Card" in query for query in GIFT_CARD_QUERIES["US"])
    assert tr["candidates"] == []
    assert tr["transport"] == "not-collected"
    assert "deferred" in tr["coverage"]


def test_ggsel_gift_card_discovery_uses_explicit_region_evidence():
    html = """
    <div data-testid="card"><a href="/catalog/product/apple-itunes-usa-102552039"></a>
      <img alt="Apple iTunes Gift Card $2-$100 USA"></div>
    <div data-testid="card"><a href="/catalog/product/apple-itunes-turkey-5211965"></a>
      <img alt="Подарочная карта Apple iTunes Turkey 10-4000 TL"></div>
    <div data-testid="card"><a href="/catalog/product/itunes-unknown-5000000"></a>
      <img alt="Apple iTunes Gift Card 2-100"></div>
    """

    us = _extract_ggsel_gift_cards(html, "US")
    tr = _extract_ggsel_gift_cards(html, "TR")

    assert [item["native_id"] for item in us] == ["102552039"]
    assert [item["native_id"] for item in tr] == ["5211965"]


def test_plati_visits_second_page_deduplicates_and_reports_coverage(monkeypatch):
    import io
    import json
    from urllib.parse import parse_qs, urlsplit
    from scanner import discover
    from dataclasses import replace

    requested = []
    def response(request, timeout):
        params = parse_qs(urlsplit(request.full_url).query)
        page = int(params['page'][0])
        requested.append(page)
        ids = ['1', '2'] if page == 1 else ['2', '3']
        return io.BytesIO(json.dumps({'content': {'items': [
            {'product_id': pid, 'name': [{'value': 'Z.ai MAX subscription 1 month'}]}
            for pid in ids
        ], 'total_pages': 2, 'total_items': 4}}).encode())
    monkeypatch.setattr(discover, 'urlopen', response)
    coverage = {}
    found, _ = discover.discover_plati(replace(ZAI, search_terms=['Z.ai']), 2, coverage=coverage)
    assert requested == [1, 2]
    assert [item['native_id'] for item in found] == ['1', '2', '3']
    assert coverage['status'] == 'ok'
    assert coverage['pagesFetched'] == 2
    assert coverage['queries'][0]['totalPages'] == 2


def test_plati_page_cap_and_later_page_failure_are_partial(monkeypatch):
    import io
    import json
    from dataclasses import replace
    from scanner import discover
    count = 0
    def response(request, timeout):
        nonlocal count
        count += 1
        if count > 1:
            raise OSError('transport unavailable')
        return io.BytesIO(json.dumps({'content': {'items': [
            {'product_id': '1', 'name': [{'value': 'Z.ai MAX subscription 1 month'}]}
        ], 'total_pages': 3}}).encode())
    monkeypatch.setattr(discover, 'urlopen', response)
    family = replace(ZAI, search_terms=['Z.ai'])
    coverage, errors = {}, []
    found, _ = discover.discover_plati(family, 1, max_pages=1, coverage=coverage)
    assert count == 1 and len(found) == 1
    assert coverage['status'] == 'partial'
    count = 0
    found, _ = discover.discover_plati(family, 1, query_errors=errors, coverage=coverage)
    assert len(found) == 1 and count == 2
    assert coverage['status'] == 'partial'
    assert errors and coverage['queries'][0]['stopReason'] == 'error'


def test_plati_total_candidate_cap_across_search_terms_is_reported(monkeypatch):
    import io
    import json
    from dataclasses import replace
    from urllib.parse import parse_qs, urlsplit
    from scanner import discover

    def response(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)['productName'][0]
        return io.BytesIO(json.dumps({'content': {'items': [
            {'product_id': query, 'name': [{'value': 'Apple Gift Card USA $5'}]}
        ], 'total_pages': 1}}).encode())

    monkeypatch.setattr(discover, 'urlopen', response)
    family = replace(ZAI, search_terms=['Apple Gift Card USA', 'iTunes Gift Card USA'])
    coverage = {}
    found, _ = discover.discover_plati(family, 10, max_total_results=1, coverage=coverage,
                                       candidate_filter=lambda label: 'Apple Gift Card' in label)
    assert len(found) == 1
    assert coverage['candidateLimit'] == 1
    assert coverage['candidateCapReached'] is True
    assert coverage['candidatesBeforeCap'] == 2
    assert coverage['candidatesReturned'] == 1
    assert coverage['status'] == 'partial'


def test_gift_discovery_includes_plati_without_denomination_floor(monkeypatch):
    from scanner import discover
    def plati(family, max_results, **kwargs):
        assert family.search_terms == list(GIFT_CARD_QUERIES['US'])
        assert kwargs['max_total_results'] == max_results
        assert kwargs['candidate_filter']('Apple Gift Card USA $5')
        assert kwargs['candidate_filter']('iTunes USA $500')
        assert not kwargs['candidate_filter']('Apple Gift Card Turkey 500 TL')
        kwargs['coverage'].update(status='ok', pagesFetched=2, queries=[])
        return [{'native_id': '1', 'source': 'plati'}], 'urllib'
    async def ggsel(*args, **kwargs):
        return []
    monkeypatch.setattr(discover, 'discover_plati', plati)
    monkeypatch.setattr(discover, '_ggsel_gift_card_search_async', ggsel)
    result = discover.discover_gift_cards('US')
    assert result['plati_found'] == 1 and result['ggsel_found'] == 0
    assert result['status'] == 'ok'
    assert result['sources']['plati']['pagesFetched'] == 2


def test_gift_discovery_distinguishes_failed_and_successful_empty(monkeypatch):
    from scanner import discover
    def plati(family, max_results, **kwargs):
        kwargs['coverage'].update(status='failed', pagesFetched=0, queries=[])
        kwargs['query_errors'].append('plati request failed')
        return [], 'urllib'
    async def ggsel(*args, **kwargs):
        raise RuntimeError('https://user:secret@proxy.invalid failure')
    monkeypatch.setattr(discover, 'discover_plati', plati)
    monkeypatch.setattr(discover, '_ggsel_gift_card_search_async', ggsel)
    result = discover.discover_gift_cards('US')
    assert result['status'] == 'failed'
    assert 'secret' not in str(result)


def test_gift_cli_failed_empty_is_nonzero_and_saved(tmp_path, monkeypatch):
    import json
    import cli
    raw_path, csv_path, md_path = tmp_path/'raw.json', tmp_path/'out.csv', tmp_path/'out.md'
    csv_path.write_text('stale offer,999 ₽\\n', encoding='utf-8')
    md_path.write_text('stale report\\n', encoding='utf-8')
    args = cli._parse_args(['--family', 'apple_gift_card', '--raw', str(raw_path),
                            '--csv', str(csv_path), '--md', str(md_path)])
    monkeypatch.setattr(cli, 'discover_gift_cards', lambda *a, **k: {
        'product': 'apple_gift_card', 'candidates': [], 'plati_found': 0, 'ggsel_found': 0,
        'status': 'failed', 'sources': {}, 'errors': ['GGSEL selector failed'], 'coverage': 'bounded',
    })
    assert cli._run_gift_card_scan(args) != 0
    assert json.loads(raw_path.read_text())['discovery']['status'] == 'failed'
    assert csv_path.read_text() == ''
    assert 'status: failed' in md_path.read_text()


def test_ggsel_search_waits_for_query_route_and_marks_empty_page():
    import asyncio
    from scanner import discover
    class Search:
        first = property(lambda self: self)
        async def fill(self, value): pass
        async def press(self, key): pass
    class Page:
        waited = False
        def get_by_placeholder(self, regex): return Search()
        async def wait_for_url(self, regex, timeout): self.waited = True
        async def wait_for_function(self, script, timeout):
            assert self.waited
        async def content(self): return '<main>По вашему запросу ничего не найдено</main>'
        def get_by_role(self, *args, **kwargs): return self
        first = property(lambda self: self)
        async def count(self): return 0
    info, found = {}, {}
    asyncio.run(discover._ggsel_gift_card_query(Page(), 'Apple Gift Card USA', 'US', 80, found, info))
    assert info['status'] == 'ok' and info['pagesFetched'] == 1
    assert found == {}


def test_gift_successful_empty_stays_ok(monkeypatch):
    from scanner import discover
    def plati(family, max_results, **kwargs):
        kwargs['coverage'].update(status='ok', pagesFetched=1, queries=[])
        return [], 'urllib'
    async def ggsel(*args, **kwargs):
        kwargs['coverage'].update(status='ok', pagesFetched=1, queries=[])
        return []
    monkeypatch.setattr(discover, 'discover_plati', plati)
    monkeypatch.setattr(discover, '_ggsel_gift_card_search_async', ggsel)
    result = discover.discover_gift_cards('US')
    assert result['candidates'] == [] and result['status'] == 'ok'
    assert result['errors'] == []


def test_partial_gift_discovery_preserves_other_source_candidates(monkeypatch):
    from scanner import discover
    def plati(family, max_results, **kwargs):
        kwargs['coverage'].update(status='ok', pagesFetched=1, queries=[])
        return [{'native_id': '1', 'source': 'plati'}], 'urllib'
    async def ggsel(*args, **kwargs):
        raise TimeoutError('selector unavailable')
    monkeypatch.setattr(discover, 'discover_plati', plati)
    monkeypatch.setattr(discover, '_ggsel_gift_card_search_async', ggsel)
    result = discover.discover_gift_cards('US')
    assert result['status'] == 'partial'
    assert result['plati_found'] == 1
    assert result['sources']['ggsel']['status'] == 'failed'


def test_plati_invalid_response_is_failed_instead_of_successful_empty(monkeypatch):
    import io
    from dataclasses import replace
    from scanner import discover
    monkeypatch.setattr(discover, 'urlopen', lambda *a, **k: io.BytesIO(b'{"error":"denied"}'))
    coverage, errors = {}, []
    found, _ = discover.discover_plati(replace(ZAI, search_terms=['Z.ai']), coverage=coverage, query_errors=errors)
    assert found == [] and coverage['status'] == 'failed' and errors
