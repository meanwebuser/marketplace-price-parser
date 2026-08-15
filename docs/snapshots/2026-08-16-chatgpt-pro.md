# Snapshot: ChatGPT Pro (own account) — 2026-08-16

**Run timestamp**: 2026-08-16 00:10–00:14 MSK (Europe/Moscow)
**Commit**: `1f9c9a7 fix(analyzer): split ChatGPT Pro X5/X20, repair stale +N ₽ prices, restore test suite`
**Raw data**: `/tmp/chatgpt_raw.json` (sha256 `ca66484f60cf90a1…`, 1 429 215 bytes, 129 listings)
**Offer rows**: 88 (24 of them are `Pro* × 1m × own_account`)

## How this snapshot was produced

```bash
# 1. Discovery + collect (6 Playwright workers) → /tmp/chatgpt_raw.json
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --purpose renew --tier Pro \
  --workers 6 --raw /tmp/chatgpt_raw.json --csv /tmp/chatgpt.csv --md /tmp/chatgpt.md

# 2. Analyzer only (no fresh scrape needed):
PYTHONPATH=. .venv/bin/python cli.py --family chatgpt --purpose renew --tier Pro \
  --skip-discover --raw /tmp/chatgpt_raw.json --csv /tmp/chatgpt.csv --md /tmp/chatgpt.md
```

## Test suite at the time of this run

```
$ PYTHONPATH=. .venv/bin/python -m pytest tests/
66 passed in 14 s
```

## Cheapest Pro on the buyer's own account (1 month)

In 2026 the marketplace Pro lineup is split into **X5** and **X20**
variants at very different price points, so they are ranked separately.
Every row is «активация/продление на ваш аккаунт» — no shared accounts,
no new-account handoffs.

| Tier              | Price       | Marketplace | Listing                                                                                                |
|-------------------|------------:|-------------|--------------------------------------------------------------------------------------------------------|
| **Pro X5**        | **8 850 ₽** | GGSEL       | [АВТО 24/7 \| Pro X5 — 1 Месяц, без входа](https://ggsel.net/catalog/product/102161789)                 |
| Pro X5 (Plati best) | 9 288 ₽   | Plati       | [АВТОВЫДАЧА. Активация / продление, Pro X5](https://plati.market/itm/5896950)                           |
| **Pro X20**       | **17 150 ₽** | GGSEL       | [АВТО 24/7 \| Pro X20 — 1 Месяц, без входа](https://ggsel.net/catalog/product/102161789)                |
| Pro X20 (Plati best) | 17 289 ₽ | Plati       | [АВТОВЫДАЧА. Активация / продление, Pro X20](https://plati.market/itm/5912754)                          |
| Pro (X not stated) | 21 975 ₽   | Plati       | [Продление ChatGPT PRO — На Ваш аккаунт, без входа](https://plati.market/itm/3714311)                   |

Bonus context from the same run: **Plus** on the buyer's own account
starts at **1 847 ₽** ([plati.market/itm/6004414](https://plati.market/itm/6004414)).

## Notable: what the pre-fix pass of this same raw data showed

- `Pro 5X × own_account` ranked at **599 ₽** (plati 5834250): the buy
  block had not refreshed after the variant click and still showed the
  listing's base-variant price, while the chip itself said
  `+11 290 ₽`. `apply_delta_correction` now recovers the real price
  (599 + 11 290 = **11 889 ₽**), and the chatgpt family rejects
  implausibly cheap Pro prices outright (floors: 3 000 ₽ for Pro/Pro 5X,
  5 000 ₽ for Pro 20X).
- All Pro variants previously collapsed into a single `Pro` bucket,
  mixing X5 (≈9–15K ₽) with X20 (≈17–25K ₽) in one ranking.
- `ChatGPT PRO 5x 1 месяц` with the title «НА ВАШ ЛЮБОЙ АККАУНТ»
  (plati 4756087, 9 800 ₽) was `unknown` delivery because the inserted
  word «ЛЮБОЙ» broke the own-account pattern; it now classifies as
  `own_account`.
- ChatGPT **Plus** offers were silently dropped entirely before this
  commit — `classify_tier` had no `Plus` rule, so the chatgpt family's
  own tier filter could never match.
