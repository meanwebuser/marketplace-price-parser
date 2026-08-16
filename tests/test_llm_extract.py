"""Tests for the LLM-as-analyzer pass 2: evidence packs (context-safe,
lossless) and the batch LLM extractor."""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.evidence import build_pack, build_batches, trim_product_area


def _listing(**over):
    base = {
        "marketplace": "ggsel", "pid": "123", "url": "https://example.test/p/123",
        "title": "Купить 24/7 | ChatGPT PRO X5 | 1 МЕСЯЦ | ЧЕРЕЗ ТОКЕН",
        "pageText": "", "descText": "", "skippedControls": [],
        "options": [], "initialPrices": [], "error": None,
    }
    base.update(over)
    return base


# ---- evidence packs: context-safe + lossless ----

def test_pack_trims_nav_and_footer_from_page_text():
    page = ("Русский\nРубли\nКаталог\nВойти\nГлавная\n" + "ПРОДУКТ: ChatGPT PRO X5 1 месяц\n"
            + "Продлить 7 999 ₽\n" + "Часто задаваемые вопросы\nПубличная оферта\nOK")
    trimmed = trim_product_area(page)
    assert "ПРОДУКТ" in trimmed and "7 999 ₽" in trimmed
    assert "Рубли" not in trimmed and "Публичная оферта" not in trimmed


def test_pack_keeps_key_evidence_and_caps_sizes():
    pack = build_pack(_listing(
        descText="Д" * 9000,
        pageText="X" * 6000,
        options=[{"text": "О" * 400, "clicked": True,
                  "prices": [{"text": "7 999 ₽", "cls": "ProductBuyBlock__amount"},
                             {"text": "115 ₽", "cls": "ProductPrice"}]}],
        skippedControls=[{"kind": "button", "text": "GO 1 МЕСЯЦ | По Токену"}],
        initialPrices=[{"text": "2 537 ₽", "cls": "ProductPrice-module__oldPrice"},
                       {"text": "7 999 ₽", "cls": "ProductBuyBlock-module__amount"}],
    ))
    assert len(pack["desc"]) <= 3500
    assert len(pack["page"]) <= 2600
    assert "GO 1 МЕСЯЦ | По Токену" in pack["skipped"]
    # prices compressed to numbers + strong flag, no CSS class strings
    s = json.dumps(pack)
    assert "ProductBuyBlock" not in s and "ProductPrice" not in s
    assert pack["opts"][0]["strong"] == 7999
    assert 7999 in pack["init_strong"]
    assert pack["err"] is None


def test_pack_flat_listing_keeps_initial_prices():
    pack = build_pack(_listing(options=[], initialPrices=[
        {"text": "983 ₽", "cls": "id_product_price"}]))
    assert pack["opts"] == []
    assert pack["init_strong"] == [983]


def test_batches_respect_char_budget():
    packs = [build_pack(_listing(pid=str(i), descText="Д" * 3000)) for i in range(10)]
    batches = build_batches(packs, max_chars=8000)
    assert all(sum(len(json.dumps(p, ensure_ascii=False)) for p in b) <= 8000 for b in batches)
    assert sum(len(b) for b in batches) == 10


# ---- LLM extractor: prompt/parse/guards ----

def test_parse_llm_content_unwraps_object_and_fences():
    from analyzer.llm_extract import _parse_llm_content
    item = {"pid": "1", "rows": []}
    assert _parse_llm_content(json.dumps([item])) == [item]
    assert _parse_llm_content(json.dumps({"items": [item]})) == [item]
    assert _parse_llm_content("```json\n" + json.dumps([item]) + "\n```") == [item]
    assert _parse_llm_content(json.dumps(item)) == [item]
    assert _parse_llm_content("no json here") is None


def test_row_to_offer_normalizes_tier_spellings_and_drops_junk():
    from analyzer.llm_extract import _row_to_offer
    pack = {"mp": "ggsel", "pid": "1", "url": "u", "title": "t",
            "opts": [{"t": "PRO X5", "c": 1, "strong": 7999, "p": []}],
            "init_strong": [7999], "init": []}
    o = _row_to_offer(pack, {"opt": "PRO X5", "tier": "Pro X5", "duration": "1m",
                             "delivery": "own_account", "price_rub": 7999}, None)
    assert o["tier"] == "Pro 5X"
    assert _row_to_offer(pack, {"tier": "Go", "duration": "1m", "delivery": "own_account",
                                "price_rub": 699}, None)["tier"] == "GO"
    assert _row_to_offer(pack, {"tier": "undefined", "duration": "1m", "delivery": "own_account",
                                "price_rub": 100}, None) is None


def test_row_to_offer_flags_price_missing_from_evidence():
    from analyzer.llm_extract import _row_to_offer
    pack = {"mp": "ggsel", "pid": "1", "url": "u", "title": "t",
            "opts": [{"t": "PRO X5", "c": 1, "strong": 7999, "p": []}],
            "init_strong": [], "init": []}
    o = _row_to_offer(pack, {"opt": "PRO X5", "tier": "Pro 5X", "duration": "1m",
                             "delivery": "own_account", "price_rub": 7777}, None)
    assert o["glitched"] is True
    assert "evidence" in o["glitch_reason"]
    ok = _row_to_offer(pack, {"opt": "PRO X5", "tier": "Pro 5X", "duration": "1m",
                              "delivery": "own_account", "price_rub": 7999}, None)
    assert ok["glitched"] is False


def test_system_prompt_defines_ready_account_wordings():
    # the LLM must see the exact wordings that mean a ready-account handover
    # and the whose-mailbox rule: buyer's email => own, seller/random => new
    from analyzer.llm_extract import SYSTEM_PROMPT
    assert "предоставляем мы" in SYSTEM_PROMPT
    assert "Создание аккаунта" in SYSTEM_PROMPT
    assert "на вашу почту" in SYSTEM_PROMPT

def _fake_completion(handler_items):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({
                "choices": [{"message": {"content": json.dumps(handler_items, ensure_ascii=False)}}]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            return
    return H


def test_extract_offers_parses_llm_rows_including_go_and_flat():
    from analyzer.llm_extract import extract_offers
    items = [{
        "pid": "123",
        "rows": [
            {"opt": "GO 1 МЕСЯЦ | По Токену", "tier": "GO", "duration": "1m",
             "delivery": "own_account", "price_rub": 699, "evidence": "GO 1 МЕСЯЦ По Токену 699"},
            {"opt": "FLAT", "tier": "Plus", "duration": "1m",
             "delivery": "new_account", "price_rub": 983, "evidence": "готовый аккаунт 983"},
        ],
    }]
    server = ThreadingHTTPServer(("127.0.0.1", 0), _fake_completion(items))
    Thread(target=server.serve_forever, daemon=True).start()
    raw = {"listings": [_listing()]}
    offers, meta = extract_offers(
        raw, api_key="k", base_url=f"http://127.0.0.1:{server.server_port}/v1",
        model="test", batch_chars=6000)
    server.shutdown()
    assert meta["called"] == 1 and meta["failed"] == 0
    tiers = {(o["tier"], o["delivery"], o["price_rub"]) for o in offers}
    assert ("GO", "own_account", 699.0) in tiers          # GO no longer lost
    assert ("Plus", "new_account", 983.0) in tiers        # flat listing ranked
    for o in offers:
        assert o["source"] == "llm"


def test_extract_offers_guards_implausible_prices():
    from analyzer.llm_extract import extract_offers
    items = [{"pid": "123", "rows": [
        {"opt": "PRO 5X", "tier": "Pro 5X", "duration": "1m", "delivery": "own_account",
         "price_rub": 599, "evidence": "stale base"}]}]
    server = ThreadingHTTPServer(("127.0.0.1", 0), _fake_completion(items))
    Thread(target=server.serve_forever, daemon=True).start()
    offers, meta = extract_offers(
        {"listings": [_listing()]}, api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}/v1", model="test",
        min_price_by_tier={"Pro 5X": 2500})
    server.shutdown()
    # hallucinated/stale 599 ₽ for Pro 5X must be flagged, not silently ranked
    assert offers[0]["glitched"] is True


def test_extract_offers_survives_bad_batch():
    from analyzer.llm_extract import extract_offers
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({"choices": [{"message": {"content": "NOT JSON"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            return
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    Thread(target=server.serve_forever, daemon=True).start()
    offers, meta = extract_offers(
        {"listings": [_listing()]}, api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}/v1", model="test")
    server.shutdown()
    assert offers == [] and meta["failed"] == 1


def test_extract_offers_retries_after_json_object_echo():
    """Regression (gemma4, 2026-08-16): with response_format=json_object the
    model echoed the input packs back; the retry without response_format
    must rescue the batch."""
    from analyzer.llm_extract import extract_offers
    good = [{"pid": "123", "rows": [
        {"opt": "GO 1 МЕСЯЦ | По Токену", "tier": "GO", "duration": "1m",
         "delivery": "own_account", "price_rub": 699, "evidence": "go token"}]}]

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            req_body = self.rfile.read(length).decode()
            if "response_format" in req_body:
                content = req_body  # echo the input packs back
            else:
                content = "```json\n" + json.dumps(good) + "\n```"
            body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            return
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    Thread(target=server.serve_forever, daemon=True).start()
    offers, meta = extract_offers(
        {"listings": [_listing()]}, api_key="k",
        base_url=f"http://127.0.0.1:{server.server_port}/v1", model="test")
    server.shutdown()
    assert meta["failed"] == 0
    assert [(o["tier"], o["price_rub"]) for o in offers] == [("GO", 699.0)]
