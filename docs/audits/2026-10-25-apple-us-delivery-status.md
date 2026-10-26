# Apple US gift-card refresh: delivery status

**Outcome:** source refresh, site data, and checks are complete; publication is pending repository-bound authorization. The independent source-backed review returned **READY**. LHC 1.5.58 accepts the reviewer outcome without importing a separate manifest, so there is no review-manifest blocker.

## Apple US data and availability

- Source snapshot: `docs/snapshots/targeted/2026-10-25-apple-us.csv` and adjacent `.raw.json`.
- The CSV contains 179 option rows. 157 have confirmed USD denomination and RUB price mappings; 22 incomplete or ineligible rows are excluded from the site.
- `docs/data/latest.json` contains 157 Apple US gift-card variants in the separate `giftCards` collection. Availability is independent from price: 155 variants have unknown stock, one is confirmed in stock, and one is confirmed out of stock. No gift-card rows are mixed into subscription products, and cards have no tier or duration fields.
- Browser proof: GGSEL listing `102662580`, variant `48277574`, seller AppleTR, selected `$50 USD` option, total **5,150 ₽** (**103 ₽ per USD**) and enabled Buy button at `2026-10-25T19:12:52Z`. The screenshot is `/tmp/apple-us-102662580-50.png`. Only this selected variant is marked in stock; sibling denominations remain unknown.
- GGSEL listing `102664570`, variant `36715426`, `$50 (USDT)` remains marked out of stock based on the captured disabled Buy button. Its price is excluded from recommendations. The lowest observed rate remains 289 ₽ for $5, or 57.80 ₽ per USD, on listing `102664570`, variant `36715422`; stock for that cheaper option is unknown.

## Same-day marketplace refresh

The five AI families were refreshed headlessly through the generic runtime-configured proxy provider. Public snapshots retain raw captures, normalized CSV, Markdown, and only non-sensitive proxy provenance. The endpoint and proxy values are not stored in public files.

| Family | Listing pages | Recognized offers | Rows in site data |
| --- | ---: | ---: | ---: |
| ChatGPT | 8 | 11 | 11 |
| Claude | 10 | 2 | 0 |
| Kimi | 17 | 47 | 39 |
| MiniMax | 12 | 33 | 33 |
| Z.ai GLM | 19 | 116 fresh + 1 separately verified | 117 |

The two Claude rows were Pro+ variants outside the supported Claude tiers, so the site publishes no Claude offers from this scan. Kimi excludes eight rows under its existing eligibility rules. The additional Z.ai GLM Max three-month offer (`102331610`, 37,000 ₽) has its own same-day evidence in `docs/snapshots/targeted/2026-10-25-zai-max.*` and `docs/audits/2026-10-25-zai-max-manual-discovery.md`.

The fresh MiniMax raw capture includes independent selected-option checks for GGSEL `102443754`: Max 1 month at 7,800 ₽, Ultra 1 month at 12,299 ₽, and Plus 1 month at 2,300 ₽. The earlier same-day capture had mismatched option prices and was not published as current; the later fresh capture and exact-option checks agree.

## Analyzer calibration and validation

On eight source-backed ChatGPT cases, deterministic regex and a one-time worker-model annotation each matched **8/8 exact rows and 32/32 field values** for tier, duration, delivery, and price. No analyzer API key was configured, so this was not an API analyzer run; the worker-model annotation is not independent human gold. The broader method and limitations are recorded in `docs/audits/2026-10-25-chatgpt-proxy-calibration.md` and `docs/audits/2026-10-25-proxy-refresh.md`.

Validation passed: Python tests **324/324**, UI tests **20/20**, focused collector CLI tests **14/14**, skill validation, syntax checks, catalogue assertions, and `git diff --check`.

## Remaining delivery gate

The user explicitly said: “Я разрешаю тебе тут публиковаться в мейн.” This authorizes main publication in the active task context, but the sentence does not name its GitHub repository. LHC 1.5.58 requires the user scope/permission quote to identify the owned repository `meanwebuser/marketplace-price-parser` (or an agreed acronym) before binding an owned `main` target. The contract therefore remains `target_scope_confirmed=false`; no branch or remote permission has been inferred from the generic phrase. Do not commit or push until a direct user instruction explicitly names both `meanwebuser/marketplace-price-parser` and `main`.
