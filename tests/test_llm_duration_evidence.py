"""A model-supplied term must be supported by the captured selected variant."""

from analyzer.evidence import build_pack
from analyzer.llm_extract import _row_to_offer
from analyzer.output import cheapest_per_tier, write_csv
from families.zai import CONFIG as ZAI
from scripts.build_pages_data import normalize_csv


def _pack(option_text="Max", *, title="Z.ai GLM Coding Max subscription", clicked=True, price=12000):
    return build_pack({
        "marketplace": "ggsel", "pid": "duration-fixture",
        "url": "https://example.test/duration", "title": title,
        "options": [{
            "text": option_text, "clicked": clicked, "selectedAfter": clicked,
            "priceVerified": clicked, "priceChanged": True, "priceStable": True,
            "prices": [{"text": f"{price} ₽", "cls": "ProductBuyBlock__amount"}],
        }],
    })


def _row(option_text="Max", *, duration="1m", price=12000, tier="Max"):
    return {"opt": option_text, "tier": tier, "duration": duration,
            "delivery": "own_account", "price_rub": price}


def test_fabricated_llm_duration_cannot_reach_normalized_catalogue_or_ranking(tmp_path):
    pack = _pack()
    for opt in ("Max", "Max 1 month"):
        # Both the duration and a possible expanded option label are invented
        # by the response; the captured option itself has no selected term.
        offer = _row_to_offer(pack, _row(opt), None)
        accepted = [] if offer is None else [offer]
        path = tmp_path / "2026-10-25-zai.csv"
        write_csv(accepted, path)
        normalized, _ = normalize_csv(path, "zai")
        assert normalized == []
        assert cheapest_per_tier(accepted, ZAI) == {}
        assert offer is None


def test_selected_year_evidence_is_preserved_and_title_cannot_supply_wrong_month():
    pack = _pack("Max 12m", title="Z.ai GLM Coding subscription 1 month", price=120000)

    yearly = _row_to_offer(pack, _row("Max 12m", duration="12m", price=120000), None)
    assert yearly is not None
    assert yearly["duration"] == "12m"
    assert not yearly["glitched"]
    assert _row_to_offer(pack, _row("Max 12m", duration="1m", price=120000), None) is None
    assert _row_to_offer(pack, _row("Max 1 month", duration="1m", price=120000), None) is None


def test_other_or_unclicked_or_ambiguous_term_is_not_selected_term_evidence():
    for pack in (
        _pack("Plus 12 months"),
        _pack("Max 12 months", clicked=False),
        _pack("Max 1/3/12 months"),
    ):
        assert _row_to_offer(pack, _row("Max 12 months", duration="12m"), None) is None


def test_paraphrased_model_label_can_use_matching_captured_tier_price_and_year():
    offer = _row_to_offer(
        _pack("Max — 1 year", price=120000),
        _row("Max annual", duration="12m", price=120000),
        None,
    )
    assert offer is not None
    assert offer["duration"] == "12m"
