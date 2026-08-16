"""ChatGPT Pro / own-account focused regression tests.

Covers the improvements made for "lowest ChatGPT Pro price on the user's
existing account": Plus tier classification, Russian Max false positives,
--purpose new-account alias, own/new delivery phrasings, and Pro-oriented
Plati search terms."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.price import (
    classify_tier,
    classify_duration,
    classify_duration_from_title,
    classify_delivery,
    apply_delta_correction,
)
from families.chatgpt import CONFIG, _build


# ---- classify_tier: ChatGPT tiers ----

def test_classify_tier_plus():
    assert classify_tier("ChatGPT Plus 1 месяц") == "Plus"
    assert classify_tier("Plus | 1 месяц") == "Plus"
    assert classify_tier("Подписка ChatGPT Плюс") == "Plus"


def test_classify_tier_chatgpt_pro():
    assert classify_tier("ChatGPT Pro - 1 Месяц") == "Pro"
    assert classify_tier("Pro (на ваш аккаунт) | 1 месяц") == "Pro"


def test_classify_tier_max_not_matched_by_maximalnaya():
    # "максимальная выгода" is marketing copy, not the Max tariff —
    # a Pro listing must not be swallowed by the Max rule.
    assert classify_tier("ChatGPT Pro 1 месяц максимальная выгода") == "Pro"
    assert classify_tier("ChatGPT Plus по максимальной цене") == "Plus"


def test_classify_tier_max_still_matches_standalone_max():
    assert classify_tier("Тариф Максимум (1 месяц)") == "Max"
    assert classify_tier("Z.ai Max 1 month") == "Max"


# ---- classify_delivery: ChatGPT phrasings ----

def test_classify_delivery_vash_akkaunt_without_na():
    assert classify_delivery("ChatGPT Pro 1 месяц (ваш аккаунт)") == "own_account"


def test_classify_delivery_na_akkaunt_pokupatelya():
    assert classify_delivery("ChatGPT Pro 1 месяц (на аккаунт покупателя)") == "own_account"


def test_classify_delivery_vash_email():
    assert classify_delivery("ChatGPT Plus 1 месяц (на ваш e-mail)") == "own_account"


def test_classify_delivery_novyy_akkaunt():
    assert classify_delivery("ChatGPT Pro 1 месяц (новый аккаунт)") == "new_account"
    assert classify_delivery("Создадим аккаунт и оформим Pro") == "new_account"


# ---- cli --purpose alias ----

def test_purpose_new_account_dash_alias():
    from cli import _parse_args, _resolve_families
    ns = _parse_args(["--family", "chatgpt", "--purpose", "new-account"])
    fam = _resolve_families(ns)[0]
    assert fam.delivery_filter == ["new_account"]


def test_purpose_unknown_rejected_cleanly():
    from cli import _parse_args, _resolve_families
    import pytest
    ns = _parse_args(["--family", "chatgpt", "--purpose", "bogus"])
    with pytest.raises(SystemExit):
        _resolve_families(ns)


# ---- family search terms: Pro coverage ----

def test_chatgpt_family_searches_pro_terms():
    terms = " | ".join(CONFIG.search_terms).lower()
    assert "chatgpt pro" in terms


def test_chatgpt_tier_filter_has_plus_and_pro():
    assert "Plus" in CONFIG.tier_filter
    assert "Pro" in CONFIG.tier_filter


def test_chatgpt_renew_preset_targets_own_account():
    fam = _build("renew")
    assert fam.delivery_filter == ["own_account"]


# ---- 2026 Pro variants: X5 / X20 are different products ----

def test_classify_tier_pro_x5():
    assert classify_tier("ChatGPT PRO 5x 1 месяц") == "Pro 5X"
    assert classify_tier("Pro X5 — 1 Месяц") == "Pro 5X"
    assert classify_tier("Продление ChatGPT PRO X5 — 1 МЕСЯЦ") == "Pro 5X"


def test_classify_tier_pro_x20():
    assert classify_tier("ChatGPT PRO 20x 1 месяц") == "Pro 20X"
    assert classify_tier("Pro X20 — 1 Месяц") == "Pro 20X"
    assert classify_tier("Продление ChatGPT PRO X20 — 1 МЕСЯЦ") == "Pro 20X"


def test_classify_tier_plain_pro_still_exists():
    assert classify_tier("Продление ChatGPT PRO — 1 МЕСЯЦ") == "Pro"
    assert classify_tier("ChatGPT Pro - 1 Месяц") == "Pro"


def test_chatgpt_family_accepts_pro_variants():
    fam = _build("renew")
    assert fam.tier_filter == ["GO", "Plus", "Pro", "Pro 5X", "Pro 20X"]


def test_chatgpt_rejects_implausibly_cheap_pro():
    """A stale base price (e.g. 599 ₽ buy block that didn't refresh after
    clicking the Pro variant) must not rank as the cheapest Pro offer."""
    fam = _build("renew")
    offer = {"tier": "Pro 5X", "duration": "1m", "delivery": "own_account",
             "glitched": False, "price_rub": 599}
    assert not fam.matches_offer(offer)
    offer["price_rub"] = 9288
    assert fam.matches_offer(offer)


# ---- "+N ₽" delta chips: buy block may still show the base variant ----

def test_delta_correction_adds_stale_base():
    assert apply_delta_correction("PRO 5X ПОДПИСКА | +11 290 ₽", 599) == 11889


def test_delta_correction_keeps_updated_price():
    # buy block already refreshed to the full variant price
    assert apply_delta_correction("PRO 20X | +19 990 ₽", 20589) == 20589
    assert apply_delta_correction("(аккаунт предоставляем мы) | +99 ₽", 10478) == 10478


def test_delta_correction_ignores_plain_options():
    assert apply_delta_correction("Pro X5 — 1 Месяц", 8850) == 8850


# ---- title-level own-account hint when the chip is silent ----

def test_title_na_vash_akkaunt_hint_beats_generic_new_hints():
    assert classify_delivery(
        "ChatGPT PRO 5x 1 месяц",
        "🏆ChatGPT - 1 месяц 5.6 PLUS | GO | PRO | НА ВАШ ЛЮБОЙ АККАУНТ✅ГАРАНТИЯ🔥",
    ) == "own_account"


# ---- GGSEL numbered chips: duration only in the title ----

def test_duration_title_fallback_unambiguous():
    # Chip carries an option number, not a duration; title says "1 МЕСЯЦ".
    assert classify_duration("1 - Продлить подписку [АВТО] | PRO X5 | ЧЕРЕЗ ТОКЕН") == ""
    assert classify_duration_from_title(
        "Купить 24/7 | ChatGPT 5.6 PRO X5 X20 | 1 МЕСЯЦ | ПОДПИСКА ЧЕРЕЗ ТОКЕН | АВТО | ЧатГПТ",
    ) == "1m"


def test_duration_title_fallback_ambiguous_stays_empty():
    # Titles naming several durations must not collapse to one guess.
    assert classify_duration_from_title(
        "Подписка GLM Coding Lite/Pro на 1/3/12 месяцев",
    ) == ""
    assert classify_duration_from_title(
        "Подписка ChatGPT 1 месяц / 12 месяцев",
    ) == ""


def test_duration_title_fallback_24_7_marker_is_not_enumeration():
    # "24/7" is support hours, not a duration list — the single "1 МЕСЯЦ"
    # in the title still resolves.
    assert classify_duration_from_title(
        "Купить 24/7 | ChatGPT 5.6 PRO X5 X20 | 1 МЕСЯЦ | ПОДПИСКА ЧЕРЕЗ ТОКЕН | АВТО",
    ) == "1m"


# ---- token / credentials delivery wording ----

def test_classify_delivery_cherez_token():
    assert classify_delivery(
        "2 - Продлить подписку [АВТО] | PRO X20 | ЧЕРЕЗ ТОКЕН",
    ) == "own_account"


def test_classify_delivery_cherez_dannye():
    assert classify_delivery(
        "3 - Продлить подписку [РУЧНАЯ] | PRO X5 | ЧЕРЕЗ ДАННЫЕ",
    ) == "own_account"


def test_offers_from_raw_keeps_numbered_ggsel_chip():
    """Regression for GGSEL 4658858: numbered chip with duration only in
    the title and token-based delivery must yield a ranked offer."""
    from analyzer.output import offers_from_raw
    raw = {"listings": [{
        "marketplace": "ggsel",
        "pid": "4658858",
        "url": "https://ggsel.net/catalog/product/4658858",
        "title": "Купить 24/7 | ChatGPT 5.6 PRO X5 X20 | 1 МЕСЯЦ | ПОДПИСКА ЧЕРЕЗ ТОКЕН | АВТО | ЧатГПТ",
        "options": [{
            "clicked": True,
            "text": "1 - Продлить подписку [АВТО]\nPRO X5\nЧЕРЕЗ ТОКЕН",
            "prices": [{"cls": "ProductBuyBlock__amount", "text": "7 999 ₽"}],
        }],
    }]}
    rows = list(offers_from_raw(raw))
    assert len(rows) == 1
    r = rows[0]
    assert (r["tier"], r["duration"], r["delivery"], r["price_rub"]) == ("Pro 5X", "1m", "own_account", 7999.0)
