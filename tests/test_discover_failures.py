"""Coverage for partial discovery failures without network or browser access."""

import json
import sys
from dataclasses import replace
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from families.kimi import CONFIG as KIMI_CONFIG
from scanner import discover


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_discover_all_preserves_partial_plati_query_failure(monkeypatch):
    family = replace(KIMI_CONFIG, search_terms=["Kimi K3", "Kimi AI"])
    response = _Response({"content": {"items": [{
        "product_id": "12345",
        "name": [{"locale": "ru-RU", "value": "Kimi K3 Ultra 1 месяц"}],
        "price": "1000",
        "seller_name": "seller",
        "total_sales": 4,
    }]}})
    monkeypatch.setattr(discover, "discover_ggsel", lambda *_args, **_kwargs: ([], "playwright"))
    with patch("scanner.discover.urlopen", side_effect=[response, URLError("TLS handshake timeout")]):
        result = discover.discover_all(family)

    assert result["plati_found"] == 1
    assert [item["native_id"] for item in result["candidates"]] == ["12345"]
    assert len(result["errors"]) == 1
    assert "Kimi AI" in result["errors"][0]
    assert "TLS handshake timeout" in result["errors"][0]
    assert result["transports"]["plati"] == "urllib"
    assert result["transports"]["platiQueryFailures"] == result["errors"]

    # Existing direct callers still receive the original two-item tuple.
    with patch("scanner.discover.urlopen", side_effect=[response, response]):
        direct_result = discover.discover_plati(family)
    assert isinstance(direct_result, tuple)
    assert len(direct_result) == 2
