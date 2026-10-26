# Apple Gift Card US discovery benchmark — 2026-10-26

Capture: 2026-10-26T02:34:14.302Z–2026-10-26T02:40:49.363Z UTC; headless, 2 collector workers; LLM calls: 0.
Proxy pool: 2000 addresses fetched from runtime config; no values stored. Final discovery status: **partial**.

## Coverage

- Queries: Apple Gift Card USA, Apple iTunes Gift Card USA, Apple Gift Card US, iTunes Gift Card US.
- Plati: 24 API pages across four queries; 178 deduplicated candidates before the 12-listing cap; 12 detail pages opened.
- GGSEL: 5 search-result pages; 15 candidates before the 12-listing cap; 12 detail pages opened.
- Parsed 489 selected denomination rows across 48 distinct denominations; 476 rows have first-pass price evidence.
- The listing set and result pages are bounded; this is not a claim of exhaustive marketplace coverage.

## Verification and publication data

- Independent final check: **failed**. The top candidate was captured at 535 ₽ for 15 USD, but a fresh selection returned 1,489 ₽. The mismatching row is `price_verified=false` and excluded from the site.
- Other captured offer rows remain available with per-row `priceVerified`, region, denomination, and button-state evidence.
- No exchange-rate conversion was inferred. Prices are RUB totals observed in the marketplace buy block.
- Availability was read from the existing product page controls; no separate stock search was performed.

## Snapshot files

- Combined website input: `docs/snapshots/targeted/2026-10-26-apple-us.csv` and `.raw.json`.
- Marketplace-specific raw/CSV captures: `2026-10-26-apple-us-plati.*` and `2026-10-26-apple-us-ggsel.*`.
- Machine-readable benchmark: `docs/audits/data/2026-10-26-apple-us-discovery.json`.
