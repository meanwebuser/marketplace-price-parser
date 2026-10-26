# GGSEL Apple US cards: effective price per face-value USD

SSR refresh window: 2026-10-25 17:34:59 UTC to 2026-10-25 17:35:47 UTC. The scope is limited to the 11 previously discovered candidate URLs. Requests ran sequentially (concurrency 1) with at most one retry for network/5xx errors; 404/410 responses were not retried. No proxy service, browser, sign-in, cart, or purchase was used.

## Method

For each available option, compute:

- **Effective price (RUB)** = server-rendered `price_wmr` + that option's `modify_value_default` in RUB.
- **RUB/USD rate** = effective price divided by the face value in USD.

Only enabled options whose label explicitly carries USD or a dollar sign enter the confirmed comparison. Options without an explicit unit remain in the CSV and raw capture but are excluded from the winner.

## Best confirmed rate

**57.8000 RUB per USD** — [Купить  Apple Gift Card США $2–$100 | Только US App Store](https://ggsel.net/catalog/product/apple-gift-card-ssa-2-100-tolko-us-app-store-102664570), listing #102664570, option **5$ (USDT)**: **289 ₽** for 5 USD (seller: FiatPay). SSR body SHA-256: `524530f5fffd3d9844bbf6e89253893669126ebcbfd58bac56555f05c91d150f`.

This is the lowest confirmed rate among the options captured from these 11 reachable candidate pages; the marketplace search is incomplete, so this is not a claim about all GGSEL listings.

## Best confirmed denomination per page

| Listing | Best option | Effective RUB | RUB/USD |
|---|---:|---:|---:|
| #5211966 | 100$ (USD) | 11232 | 112.3200 |
| #102664570 | 5$ (USDT) | 289 | 57.8000 |
| #102552039 | 5 USD | 319 | 63.8000 |
| #4852424 | 14 $ (USD) | 1455.67 | 103.9764 |
| #102724474 | 5 USD | 690 | 138.0000 |
| #102662580 | 15+75=90 USD | 9030 | 100.3333 |
| #102691390 | 2 USD | 199 | 99.5000 |
| #5162399 | unavailable / no confirmed USD option | — | — |
| #102708567 | 100 USD | 11278 | 112.7800 |
| #102083320 | 70 USD | 11498 | 164.2571 |
| #102163314 | 2 USD | 205 | 102.5000 |

## Coverage and artifacts

- Existing discovery set: 19 candidate IDs. This bounded refresh queried 11 previously live URLs; 11 returned HTTP 200, 0 were unavailable.
- No new search queries were issued; total catalogue coverage remains incomplete.
- The raw JSON keeps each SSR response hash, base RUB price, seller, and every denomination variant with its surcharge and computed total. Full HTML bodies are not embedded.
- The CSV has one row per option, including unavailable-unit/mapping cases.

Files: `docs/snapshots/targeted/2026-10-25-apple-us.raw.json`, `docs/snapshots/targeted/2026-10-25-apple-us.csv`, `docs/audits/data/2026-10-25-apple-us-manual-discovery.json`.

## Availability refresh

Captured 2026-10-25T17:56:21Z with direct, sequential public SSR GETs (no proxy). Checked 72 option rows across #102664570 and the three best alternative listings #102552039, #102691390, and #102163314.

- SSR exposes no per-option stock signal for these pages: every checked option has `num_in_stock=null` and `disabled=null`; rendered controls are not disabled. Therefore 71 rows are `unknown`, not confirmed in stock.
- The user-provided screenshot shows only #102664570 option `50$ (USDT)` as «Нет в наличии»; that single row is marked `out_of_stock` with screenshot-only evidence.
- The price-ratio leader remains #102664570 `5$ (USDT)`, 289 ₽, 57.80 ₽ per face USD, but its availability is unknown. No currently available winner can be proven from these sources.
- Proxy preflight: SSH `bezrabotnyi.com:22104` identified `roomhacker-server-100`. The SearXNG pool at `127.0.0.1:18090` returned HTTP 401 for four sequential GETs; direct SSR was used for the availability observations. No secrets or proxy upstream values were read or exposed. `latest.json` was left untouched because this evidence does not fit the existing subscription-offer projection safely.
