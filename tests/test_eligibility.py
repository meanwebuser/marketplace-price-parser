"""Tests for family eligibility filtering and delivery classification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from families import FAMILY_REGISTRY
from families.base import FamilyConfig
from analyzer.price import classify_tier, classify_duration, classify_delivery


# ---- classify_tier ----

def test_classify_tier_max():
    assert classify_tier("GLM Coding Max 1 month") == "Max"
    assert classify_tier("Z.ai Lite/Pro/Max") == "Max"


def test_classify_tier_pro_plus():
    assert classify_tier("Pro+ subscription") == "Pro+"
    assert classify_tier("GLM Coding Pro+ 1 month") == "Pro+"


def test_classify_tier_pro():
    assert classify_tier("Pro 1 month") == "Pro"
    assert classify_tier("GLM Coding Pro") == "Pro"


def test_classify_tier_lite():
    assert classify_tier("Lite 1 month") == "Lite"


def test_classify_tier_unknown():
    assert classify_tier("Random product") == ""


# ---- classify_duration ----

def test_classify_duration_1m():
    assert classify_duration("1 месяц") == "1m"
    assert classify_duration("1 month") == "1m"
    assert classify_duration("1m") == "1m"
    assert classify_duration("30 дней") == "1m"


def test_classify_duration_3m():
    assert classify_duration("3 месяца") == "3m"
    assert classify_duration("3 months") == "3m"
    assert classify_duration("90 дней") == "3m"


def test_classify_duration_12m():
    assert classify_duration("1 год") == "12m"
    assert classify_duration("12 months") == "12m"
    assert classify_duration("1 year") == "12m"
    assert classify_duration("365 дней") == "12m"


def test_classify_duration_unknown():
    assert classify_duration("random") == ""


# ---- classify_delivery ----

def test_classify_delivery_own_account():
    assert classify_delivery("Апгрейд/Продление: Z.ai Max (Требуется Вход)") == "own_account"
    assert classify_delivery("Upgrade on your personal account") == "own_account"
    assert classify_delivery("Max - 1 Месяц (на ваш аккаунт)") == "own_account"


def test_classify_delivery_new_account():
    assert classify_delivery("Аккаунт Z.ai - 1 Месяц (Случайный Email)") == "new_account"
    assert classify_delivery("Готовый аккаунт") == "new_account"
    assert classify_delivery("Персональный аккаунт") == "new_account"


def test_classify_delivery_shared_account():
    assert classify_delivery("Общий аккаунт - 1 месяц") == "shared_account"
    assert classify_delivery("Общий доступ подписка") == "shared_account"


def test_classify_delivery_unknown():
    assert classify_delivery("обычное название без маркеров") == "unknown"


def test_classify_delivery_title_hints_new_account():
    # chip "Max | 1 месяц" alone is silent, title "Мгновенный доступ" => new_account
    assert classify_delivery("Max | 1 месяц",
                             "Z.AI | Lite • Pro • Max | Мгновенный доступ") == "new_account"
    assert classify_delivery("Max | 1 месяц",
                             "Официальная активация") == "new_account"


def test_classify_delivery_first_month_offer():
    # (предложение на первый месяц) => new_account (first-month promo)
    assert classify_delivery("GLM Coding MAX | 1 месяц (предложение на первый месяц)",
                             "anything") == "new_account"


def test_classify_delivery_known_own_still_wins_over_title():
    # chip with explicit own-account marker wins over title hint
    assert classify_delivery("Апгрейд/Продление: Z.ai GLM Coding Max - 1 Месяц (Требуется Вход)",
                             "Мгновенный доступ") == "own_account"


def test_classify_delivery_title_mgnovennaya_aktivatsiya():
    assert classify_delivery("Тариф «Макс» (1 месяц)",
                             "Z.AI | Премиум-доступ к ИИ | 1 месяц | Мгновенная активация") == "new_account"


def test_classify_delivery_title_operativnaya_podderzhka():
    assert classify_delivery("Тариф «Макс» | 1 месяц |",
                             "Z.AI | Подписка на 1 месяц — оперативная поддержка и гарантийное обслуживание") == "new_account"


def test_classify_delivery_title_garantiya_100():
    assert classify_delivery("Max | 1 месяц",
                             "Подписка Z.AI (1 месяц) 💎 Гарантия 100% | Официальная активация") == "new_account"


def test_classify_delivery_title_24_7():
    assert classify_delivery("Max | 1 месяц",
                             "Подписка с поддержкой 24/7 и моментальной выдачей") == "new_account"


def test_classify_delivery_title_neutral_stays_unknown():
    # No delivery markers anywhere — stay honest, leave as unknown
    assert classify_delivery("Max 1 месяц",
                             "Подписка GLM Coding Lite/Pro на 1/3/12 месяцев") == "unknown"


def test_classify_delivery_title_prolong_podpisk():
    # Chip with own-account chip marker is authoritative
    assert classify_delivery("Продление подписки Z.ai Max 1 месяц",
                             "Обновление подписки на ваш аккаунт") == "own_account"


# ---- FamilyConfig.matches_offer ----

def _offer(tier, duration, delivery, glitched=False):
    return {"tier": tier, "duration": duration, "delivery": delivery, "glitched": glitched}


def test_zai_accepts_max_1m_own_account():
    zai = FAMILY_REGISTRY["zai"]
    assert zai.matches_offer(_offer("Max", "1m", "own_account"))


def test_zai_rejects_lite():
    zai = FAMILY_REGISTRY["zai"]
    assert not zai.matches_offer(_offer("Lite", "1m", "own_account"))


def test_zai_rejects_shared_account_by_default():
    zai = FAMILY_REGISTRY["zai"]
    assert not zai.matches_offer(_offer("Max", "1m", "shared_account"))


def test_zai_rejects_glitched():
    zai = FAMILY_REGISTRY["zai"]
    assert not zai.matches_offer(_offer("Max", "1m", "own_account", glitched=True))


def test_chatgpt_renew_excludes_shared():
    from families.chatgpt import _build
    fam = _build("renew")
    assert fam.matches_offer(_offer("Plus", "1m", "own_account"))
    assert not fam.matches_offer(_offer("Plus", "1m", "shared_account"))
    assert not fam.matches_offer(_offer("Plus", "1m", "new_account"))


def test_chatgpt_new_account_excludes_own():
    from families.chatgpt import _build
    fam = _build("new_account")
    assert fam.matches_offer(_offer("Plus", "1m", "new_account"))
    assert not fam.matches_offer(_offer("Plus", "1m", "own_account"))
    assert not fam.matches_offer(_offer("Plus", "1m", "shared_account"))


def test_chatgpt_any_accepts_both():
    from families.chatgpt import _build
    fam = _build("any")
    assert fam.matches_offer(_offer("Plus", "1m", "own_account"))
    assert fam.matches_offer(_offer("Plus", "1m", "new_account"))
    assert not fam.matches_offer(_offer("Plus", "1m", "shared_account"))


def test_minimax_rejects_3m():
    minimax = FAMILY_REGISTRY["minimax"]
    assert minimax.matches_offer(_offer("Max", "1m", "own_account"))
    assert not minimax.matches_offer(_offer("Max", "3m", "own_account"))


def test_eligibility_extra_callback():
    cfg = FamilyConfig(
        name="custom",
        search_terms=["custom"],
        purpose_preset="any",
        marketplaces=["plati"],
        tier_filter=["Max"],
        duration_filter=["1m"],
        delivery_filter=["own_account"],
        eligibility_extra=lambda o: o.get("price_rub", 99999) < 20000,
    )
    assert cfg.matches_offer({**_offer("Max", "1m", "own_account"), "price_rub": 15000})
    assert not cfg.matches_offer({**_offer("Max", "1m", "own_account"), "price_rub": 25000})


def test_llm_overrides_unknown_delivery():
    from analyzer.llm import apply_llm_reviews
    items = [{"url": "x", "tier": "Max", "duration": "1m", "delivery": "unknown", "price_rub": 15000}]
    reviews = {"x": {"tier": "Max", "duration": "1m", "delivery": "own_account", "price_rub": 15000}}
    apply_llm_reviews(items, reviews, override_unknowns=True)
    assert items[0]["delivery"] == "own_account"
    assert items[0]["llm_overrode"] is True


def test_llm_does_not_override_known_delivery():
    from analyzer.llm import apply_llm_reviews
    items = [{"url": "x", "tier": "Max", "duration": "1m", "delivery": "own_account", "price_rub": 15000}]
    reviews = {"x": {"tier": "Max", "duration": "1m", "delivery": "new_account", "price_rub": 15000}}
    apply_llm_reviews(items, reviews, override_unknowns=True)
    # LLM should NOT overwrite a confident own_account with new_account
    assert items[0]["delivery"] == "own_account"
    assert "llm_overrode" not in items[0]


def test_llm_flags_price_mismatch():
    from analyzer.llm import apply_llm_reviews
    items = [{"url": "x", "tier": "Max", "duration": "1m", "delivery": "own_account", "price_rub": 15000}]
    reviews = {"x": {"tier": "Max", "duration": "1m", "delivery": "own_account", "price_rub": 25000}}
    apply_llm_reviews(items, reviews, override_unknowns=False)
    assert "warning" in items[0]
    assert "Gemma reported 25000" in items[0]["warning"]

def test_llm_title_fallback_to_new_account():
    """When both analyzer and LLM say unknown, infer new_account from title
    (no own-account markers)."""
    from analyzer.llm import apply_llm_reviews
    items = [{"url": "x", "title": "Z.AI | Lite • Pro • Max | Подписка на 1 месяц",
              "tier": "Max", "duration": "1m", "delivery": "unknown", "price_rub": 15000}]
    reviews = {"x": {"tier": "Max", "duration": "1m", "delivery": "unknown", "price_rub": 15000}}
    apply_llm_reviews(items, reviews, override_unknowns=True)
    assert items[0]["delivery"] == "new_account"
    assert items[0]["llm_overrode"] is True
    assert "delivery=new_account*" in items[0]["llm_overrode_fields"]


def test_llm_title_fallback_promotes_own_listing():
    """When title has own-account markers ("Продление", "на ваш аккаунт"),
    the heuristic must promote unknown -> own_account (not new_account)."""
    from analyzer.llm import apply_llm_reviews
    items = [{"url": "x", "title": "Продление подписки Z.AI Max",
              "tier": "Max", "duration": "1m", "delivery": "unknown", "price_rub": 18000}]
    reviews = {"x": {"tier": "Max", "duration": "1m", "delivery": "unknown", "price_rub": 18000}}
    apply_llm_reviews(items, reviews, override_unknowns=True)
    # Title has "Продление" — heuristic should promote unknown -> own_account
    assert items[0]["delivery"] == "own_account"
    assert "delivery=own_account*" in items[0]["llm_overrode_fields"]


def test_llm_title_fallback_promotes_na_vash_akkaunt():
    """Title 'НА ВАШ АККАУНТ' must infer own_account, not new_account."""
    from analyzer.llm import apply_llm_reviews
    items = [{"url": "x", "title": "1-12 МЕСЯЦЕВ ПОДПИСКИ Z.AI / НА ВАШ АККАУНТ",
              "tier": "Max", "duration": "1m", "delivery": "unknown", "price_rub": 18000}]
    reviews = {"x": {"tier": "Max", "duration": "1m", "delivery": "unknown", "price_rub": 18000}}
    apply_llm_reviews(items, reviews, override_unknowns=True)
    assert items[0]["delivery"] == "own_account"


def test_classify_delivery_neutral_title_chip_only():
    """Truly neutral listing: no chip markers, no title markers -> unknown."""
    assert classify_delivery("Max 1 месяц", "Подписка GLM Coding Lite/Pro на 1/3/12 месяцев") == "unknown"