"""Evidence packs: compact, context-safe per-listing digests of the raw
collector JSON, built so a batch LLM analyzer loses nothing that matters
while nav/footer noise and CSS-class bloat stay out of the prompt.

Design constraints (from the 2026-08-16 audit data, 130 listings):
- full raw JSON is ~2.3 MB — mostly pageText nav/footer junk (587 KB) and
  long CSS class names inside price records (121 KB);
- a pack must fit ~3 KB avg so a 24 KB batch ≈ 10 listings ≈ ~9K tokens,
  one independent call per batch — context never accumulates."""

from __future__ import annotations

import json
import re
from typing import Iterable

PAGE_CAP = 2500
DESC_CAP = 3500
TITLE_CAP = 200
OPT_TEXT_CAP = 180
OPT_PRICES_CAP = 6
INIT_PRICES_CAP = 4
SKIPPED_TOTAL_CAP = 600
SKIPPED_ITEM_CAP = 80

# Page regions past the product block: marketing/FAQ/footer starts here.
_PAGE_END_MARKERS = (
    "Часто задаваемые вопросы",
    "Похожие товары",
    "Похожие предложения",
    "Публичная оферта",
    "Политика конфиденциальности",
    "Информация для правообладателей",
    "Вопросы и ответы",
    "Все права защищены",
    "Используем cookies",
)

# Exact nav/header lines seen on both marketplaces (whitespace-trimmed).
_NAV_EXACT_LINES = {
    "Русский", "Рубли", "Начать продавать", "Каталог", "Избранное", "Заказы",
    "Войти", "Донат", "Главная", "OK", "Поддержка", "Скидки 90%", "Игры",
    "Apple карты", "Roblox", "CS2 Market", "Пополнение Steam", "Пополнение PSN",
}

_PRICE_NUM_RE = re.compile(r"\d[\d\s\xa0]*")


def _is_strong_price(cls: str) -> bool:
    c = (cls or "").lower()
    return ("buyblock" in c and "amount" in c) or "id_product_price" in c


def _price_num(text: str) -> int | None:
    m = _PRICE_NUM_RE.search(text or "")
    if not m:
        return None
    try:
        return int(m.group(0).replace(" ", "").replace("\xa0", ""))
    except ValueError:
        return None


def trim_product_area(page_text: str) -> str:
    """Drop footer/FAQ tail and exact-match nav lines; cap the rest."""
    if not page_text:
        return ""
    t = page_text
    for marker in _PAGE_END_MARKERS:
        i = t.find(marker)
        if i > 0:
            t = t[:i]
    lines = [ln for ln in t.split("\n") if ln.strip() not in _NAV_EXACT_LINES]
    return "\n".join(lines)[:PAGE_CAP]


def _pack_option(opt: dict) -> dict:
    strong = None
    nums: list[int] = []
    for p in opt.get("prices", []) or []:
        n = _price_num(p.get("text", ""))
        if n is None:
            continue
        if _is_strong_price(p.get("cls", "")) and strong is None:
            strong = n
        if n not in nums and len(nums) < OPT_PRICES_CAP:
            nums.append(n)
    return {
        "t": (opt.get("text") or "")[:OPT_TEXT_CAP],
        "c": 1 if opt.get("clicked") else 0,
        "strong": strong,
        "p": nums,
    }


def build_pack(listing: dict) -> dict:
    skipped: list[str] = []
    used = 0
    for s in listing.get("skippedControls") or []:
        t = (s.get("text") or "").strip()[:SKIPPED_ITEM_CAP]
        if not t or used + len(t) > SKIPPED_TOTAL_CAP:
            continue
        skipped.append(t)
        used += len(t) + 2

    init_strong: list[int] = []
    init_other: list[int] = []
    for p in listing.get("initialPrices") or []:
        n = _price_num(p.get("text", ""))
        if n is None:
            continue
        if _is_strong_price(p.get("cls", "")):
            if n not in init_strong and len(init_strong) < 2:
                init_strong.append(n)
        elif n not in init_other and len(init_other) < INIT_PRICES_CAP:
            init_other.append(n)

    return {
        "pid": str(listing.get("pid", "")),
        "mp": listing.get("marketplace", ""),
        "url": listing.get("url", ""),
        "title": (listing.get("title") or "")[:TITLE_CAP],
        "desc": (listing.get("descText") or "")[:DESC_CAP],
        "page": trim_product_area(listing.get("pageText") or ""),
        "opts": [_pack_option(o) for o in listing.get("options") or []],
        "skipped": skipped,
        "init_strong": init_strong,
        "init": init_other,
        "err": listing.get("error"),
    }


def build_batches(packs: Iterable[dict], max_chars: int) -> list[list[dict]]:
    """Greedy pack-by-pack batching under a char budget per batch. A single
    oversized pack still forms its own batch (never silently dropped)."""
    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for p in packs:
        n = len(json.dumps(p, ensure_ascii=False))
        if cur and cur_len + n > max_chars:
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += n
    if cur:
        batches.append(cur)
    return batches
