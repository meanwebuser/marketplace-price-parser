import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# minimax_max_prices is now a package: the __init__.py is a thin
# wrapper that delegates to cli.py, and .legacy holds the original
# implementation. We import the legacy module directly so the existing
# tests keep validating the original (hand-curated + Gemma4) logic.
from minimax_max_prices import legacy as minimax_max_prices
# scanner/discover.py replaced minimax_discovery in the live pipeline, but
# minimax_max_prices.legacy still imports it, so it must stay importable.
import minimax_discovery


def test_official_offer_is_selected_for_existing_account():
    config = minimax_max_prices.load_candidates()
    official = minimax_max_prices.official_offer(config["official"])
    marketplace = {
        "source": "plati",
        "label": "seller",
        "url": "https://example.test/minimax",
        "price": 26000,
        "currency": "RUB",
        "delivery": "own-login",
        "product_family": "hailuo-minimax-legacy",
        "status": "ok",
        "llm_review": {
            "verdict": "eligible",
            "product_family": "hailuo-minimax-legacy",
            "plan": "max",
            "term_months": 1,
            "account_delivery": "existing-account-login",
            "availability": "available",
        },
    }
    offers = minimax_max_prices.enrich_prices([official, marketplace], 78.0308)
    eligible = sorted(
        (offer for offer in offers if offer["eligible_existing_account"]),
        key=lambda offer: offer["price_rub"],
    )
    assert eligible[0]["source"] == "official"
    assert eligible[0]["price_rub"] == 3901.54
    assert marketplace["eligible_existing_account"] is False


def test_cli_skip_marketplaces_is_an_integration_smoke():
    completed = subprocess.run(
        [sys.executable, "-m", "minimax_max_prices.legacy", "--skip-marketplaces", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["best"]["source"] == "official"
    assert result["best"]["price_rub"] == 3901.54


def test_marketplace_crawler_failure_is_reported_without_secrets():
    with patch("minimax_max_prices.legacy.subprocess.run") as run:
        run.return_value.returncode = 1
        run.return_value.stderr = "browser failed"
        run.return_value.stdout = ""
        result = minimax_max_prices.crawl_marketplaces([{"source": "plati", "label": "x", "url": "https://example.test"}])
    assert result[0]["status"] == "error"
    assert "browser failed" in result[0]["error"]


def test_gemma_openai_compatible_http_integration():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            response = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "offers": [
                                        {
                                            "url": "https://example.test/minimax",
                                            "product_family": "minimax-token-plan",
                                            "plan": "max",
                                            "term_months": 1,
                                            "account_delivery": "existing-account-login",
                                            "final_price": 4084,
                                            "currency": "RUB",
                                            "availability": "available",
                                            "verdict": "eligible",
                                            "confidence": 0.99,
                                            "reason": "selected Max one-month option on existing account",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        reviews, meta = minimax_max_prices.review_with_gemma(
            [
                {
                    "source": "plati",
                    "url": "https://example.test/minimax",
                    "title": "MiniMax Max",
                    "price": 4084,
                    "currency": "RUB",
                    "status": "ok",
                    "plan_label": "Max 1 month",
                    "delivery_label": "existing account",
                    "price_text": "4084 RUB",
                    "evidence": {"accessibility_tree": []},
                }
            ],
            "test-key",
            f"http://127.0.0.1:{server.server_port}/v1",
            "gemma4",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert meta["status"] == "ok"
    assert reviews["https://example.test/minimax"]["verdict"] == "eligible"


def test_browser_crawler_selects_max_on_existing_account_fixture():
    html = """
    <!doctype html>
    <html><head><title>MiniMax AI Platform API Max</title></head>
    <body>
      <h1>MiniMax AI Platform API Plus/Max/Ultra</h1>
      <button value="plus" data-group="plan" aria-pressed="true">Plus 1 Month</button>
      <button value="max" data-group="plan" aria-pressed="false">Max 1 Month</button>
      <button value="available" data-group="account" aria-pressed="true">Available Account</button>
      <button value="existing" data-group="account" aria-pressed="false">Activated on your account</button>
      <div id="product_price2">1 200 ₽</div>
      <script>
        const buttons = [...document.querySelectorAll('button[value]')];
        function updatePrice() {
          const max = document.querySelector('button[value="max"]').getAttribute('aria-pressed') === 'true';
          const existing = document.querySelector('button[value="existing"]').getAttribute('aria-pressed') === 'true';
          document.querySelector('#product_price2').textContent = max && existing ? '4 333 ₽' : '1 200 ₽';
        }
        buttons.forEach((button) => button.addEventListener('click', () => {
          buttons.filter((candidate) => candidate.dataset.group === button.dataset.group)
            .forEach((candidate) => candidate.setAttribute('aria-pressed', candidate === button ? 'true' : 'false'));
          updatePrice();
        }));
      </script>
    </body></html>
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = subprocess.run(
            [
                "node",
                str(ROOT / "minimax_browser_crawler.js"),
                "--url",
                f"http://127.0.0.1:{server.server_port}/minimax",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    item = json.loads(completed.stdout)["items"][0]
    assert item["status"] == "ok"
    assert item["price"] == 4333
    assert item["delivery"] == "own-login"
    assert item["plan_label"] == "Max 1 Month"
    assert item["delivery_label"] == "Activated on your account"
    assert item["product_family"] == "minimax-token-plan"


def test_auto_discovery_integrates_plati_api_and_ggsel_category():
    detail_html = """
    <!doctype html>
    <html><head><title>MiniMax API Platform Max</title></head>
    <body>
      <h1>MiniMax API Platform Plus Max 1 Month</h1>
      <button value="plus" data-group="plan" aria-pressed="true">Plus 1 Month</button>
      <button value="max" data-group="plan" aria-pressed="false">Max 1 Month</button>
      <button value="available" data-group="account" aria-pressed="true">Available Account</button>
      <button value="existing" data-group="account" aria-pressed="false">Activated on your account</button>
      <div id="product_price2">1 200 ₽</div>
      <script>
        const buttons = [...document.querySelectorAll('button[value]')];
        function updatePrice() {
          const max = document.querySelector('button[value="max"]').getAttribute('aria-pressed') === 'true';
          const existing = document.querySelector('button[value="existing"]').getAttribute('aria-pressed') === 'true';
          document.querySelector('#product_price2').textContent = max && existing ? (location.pathname.startsWith('/itm/') ? '2 100 ₽' : '2 200 ₽') : '1 200 ₽';
        }
        buttons.forEach((button) => button.addEventListener('click', () => {
          buttons.filter((candidate) => candidate.dataset.group === button.dataset.group)
            .forEach((candidate) => candidate.setAttribute('aria-pressed', candidate === button ? 'true' : 'false'));
          updatePrice();
        }));
      </script>
    </body></html>
    """
    api_payload = {
        "content": {
            "items": [
                {
                    "product_id": 123,
                    "name": [{"locale": "ru-RU", "value": "MiniMax API Platform Plus Max 1 Month"}],
                    "name_url": "fixture-minimax-api-platform-plus-max-1-month",
                    "price": 1000,
                    "seller_name": "fixture-seller",
                    "total_sales": 3,
                }
            ]
        }
    }
    category_html = """
    <!doctype html>
    <html><body>
      <a data-testid="card-link" href="/catalog/product/fixture-ggsel-minimax-max-1-month">
        <div class="ProductCard-fixture-card"><div>1 100 ₽</div><div>MiniMax API Platform Plus Max 1 Month</div></div>
      </a>
    </body></html>
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/cataloguer/front/products"):
                body = json.dumps(api_payload).encode("utf-8")
                content_type = "application/json"
            elif self.path.startswith("/catalog/minimaxhailuo"):
                body = category_html.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            else:
                body = detail_html.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    fixture_base = f"http://127.0.0.1:{server.server_port}"
    env.update(
        {
            "MINIMAX_GGSEL_CATEGORY_URL": f"{fixture_base}/catalog/minimaxhailuo",
            "MINIMAX_PLATI_API_URL": f"{fixture_base}/api/cataloguer/front/products",
            "MINIMAX_PLATI_BASE_URL": fixture_base,
        }
    )
    try:
        with patch.dict(os.environ, env, clear=False), patch.object(minimax_discovery, "_load_impit", return_value=None):
            candidates, metadata = minimax_discovery.discover_marketplaces("MiniMax", 10)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert metadata["plati_found"] == 1
    assert metadata["ggsel_found"] == 1
    candidates_by_source = {candidate["source"]: candidate for candidate in candidates}
    assert candidates_by_source["plati"]["catalog_price_rub"] == 1000
    assert candidates_by_source["ggsel"]["catalog_price_rub"] == 1100
