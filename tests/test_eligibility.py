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
