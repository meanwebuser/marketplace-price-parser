# Marketplace discovery benchmark — 2026-10-23

## Scope and result

This is a bounded manual UI benchmark of Plati and GGSEL discovery for MiniMax and Claude. It records the visible results from one headless browser session per route, the exact UI searches, page/card counts, offer IDs, and access or pagination failures. It is a reproducible sample, not an exhaustive marketplace census. Do not interpret a category result count or an unresponsive “show more” button as a total inventory count.

The observed GGSEL Claude subcategories are much larger than the current catalogue's five unique GGSEL Claude listing URLs: the Max 5x category rendered 43 unique listing links and the fully hydrated Max 20x list rendered 23 Claude-tagged links. The general Claude and Claude Pro pages each showed 60 unique listing links with a “Показать ещё” control. Repeated clicks on the general Claude control did not load more results; the Pro control was observed but not clicked. Neither page is exhausted. Plati could not be searched because it returned HTTP/browser-visible 403 errors from both permitted hosts. GGSEL's homepage search field returned no MiniMax suggestions for the tested aliases, and the loaded services-category sample contained no MiniMax-like card.

## Run environment

| Date | Host | Browser session | Mode | Entry route |
|---|---|---|---|---|
| 2026-10-23 | `server-44` | `lp-audit-20261023` | `/usr/bin/agent-browser`, headless | GGSEL home and category pages |
| 2026-10-23 | `server-44` | `lp-audit-plati` | `/usr/bin/agent-browser`, headless | Plati home and existing listing `6175989` |
| 2026-10-23 | `roomhacker-server-88` | `lp-audit-plati88` | `/usr/bin/agent-browser`, headless | Plati home |

The browser was launched over SSH on the approved server-44/server-88 routes. No login, checkout, purchase, or user desktop window was used. Exact session start times were not captured; date precision is one day. Each task-owned session was closed after the pass.

## Current site-catalogue baseline

Counts below come from `docs/data/latest.json` on 2026-10-23. “Rows” count normalized offer-option rows; “unique URLs” count distinct seller listings after grouping tier/option variants by URL. They are not marketplace totals.

| Service | Normalized rows | Unique listing URLs | Plati unique URLs | GGSEL unique URLs |
|---|---:|---:|---:|---:|
| MiniMax | 15 | 3 | 3 | 0 |
| Claude | 36 | 18 | 13 | 5 |

The five current GGSEL Claude listing IDs are `102630496`, `102630410`, `102337106`, `102630428`, and `102659591`. The selected Max 5x/Max 20x examples below are not among those five IDs. A full ID-by-ID crosswalk of every category card was not performed. The absence of GGSEL MiniMax rows is not proof that GGSEL has no MiniMax offers.

## Marketplace UI observations

| Marketplace / page | UI action | Initial visible sample | After interaction | Matching result / coverage |
|---|---|---:|---:|---|
| Plati, `https://plati.market/` on server-44 | Open homepage | 403 page, 0 offer cards | Not applicable | Search blocked by visible `403 - Forbidden`; no catalogue coverage established |
| Plati, `https://plati.market/itm/6175989` on server-44 | Open an existing Claude listing directly | 403 page, 0 offer cards | Not applicable | Direct listing also blocked |
| Plati, `https://plati.market/` on server-88 | Open homepage in a separate headless session | 403 page, 0 offer cards | Not applicable | Same blocker on the second permitted host; no search or pagination evidence |
| GGSEL, `https://ggsel.net/catalog/claudeai` | Open Claude category from the visible Claude category link | 60 distinct `/catalog/product/` URLs; “Показать ещё” visible | Repeated UI clicks/scroll-to-button attempts left the list at 60; button remained | Partial first-page/category sample; pagination is unverified and not exhausted |
| GGSEL, `https://ggsel.net/catalog/claude-ai-pro` | Open Pro subcategory | 60 distinct `/catalog/product/` URLs; “Показать ещё” visible | No click performed on this route | Partial loaded page; no exhaustion claim |
| GGSEL, `https://ggsel.net/catalog/claude-ai-max-5x` | Open Max 5x subcategory | 43 distinct `/catalog/product/` URLs; no “Показать ещё” button in the observed snapshot | No further page control visible | Bounded loaded category sample; absence of a button does not prove all inventory is shown |
| GGSEL, `https://ggsel.net/catalog/claude-ai-max-20x` | Open Max 20x subcategory | First accessibility snapshot had 11 unique URLs before full render; after the list finished rendering, 23 distinct Claude-tagged offer cards were visible (25 cards total in that collection, including two unrelated cross-sells) | No “Показать ещё” button in the observed category snapshot | Use 23 Claude-tagged links as the hydrated sample count; not a marketplace total |
| GGSEL, `https://ggsel.net/catalog/podpisochnye-servisy` | Inspect loaded product list and use in-page text find | 60 visible product-card nodes; “Показать ещё” visible | One click after scrolling into view left count at 60 and button remained | Partial category sample, not an AI-only category and not exhausted |

The service-category page's metadata described a much larger underlying marketplace category, while its current rendered list contained only the 60-card sample above. The metadata is not used as a count of verified MiniMax or Claude offers.

## Search and Find terms

### GGSEL homepage search field

The visible `Найти товар` field was filled with `MiniMax`, `Минимакс`, `MiniMax Token Plan`, and `Claude`. For `MiniMax`, Enter and a click on the search icon were also tried. The URL stayed on the homepage; no query-specific suggestions or results appeared. The field's static category shortcuts remained visible. Therefore these are recorded as attempted queries with no returned search-result surface, not as zero-result searches.

The public services-category page at `https://ggsel.net/catalog/podpisochnye-servisy` had no MiniMax category link. This is a bounded navigation check, not proof that no alternate route or listing exists.

### GGSEL services-category in-page Find

On the 60-card loaded sample, the in-page text Find was run for `MiniMax`, `Минимакс`, `Hailuo`, `abab`, `Claude`, and `Клод`. No MiniMax/Hailuo/abab/Клод product-card match was found. `Claude` occurred in the visible category shortcut and page hydration data, not as a matching offer card in this loaded sample.

## Selected listing evidence

Prices in the table are copied from the category cards. The tested detail page did not expose a numeric price in its rendered body, so no category-card price below is labelled as detail-page verified.

| Marketplace | ID | Visible title | Term shown | Category-card price | Detail-page result | URL |
|---|---|---|---|---:|---|---|
| GGSEL | `102530215` | `[24/7 | АВТО] Claude AI FABLE 5.0 | MAX 20X | Подписка AI | 1 МЕСЯЦ | Клод АИ` | 1 month | 29,999 ₽ | Opened from the category; title and seller description confirmed Max 20x / one month; no numeric price visible on detail page | [Listing](https://ggsel.net/catalog/product/24-7-avto-claude-ai-fable-5-0-max-20x-podpiska-ai-1-mesiac-klod-ai-102530215) |
| GGSEL | `102501829` | `АВТО | Claude AI FABLE 5.5 | MAX 20X | Подписка AI 1 МЕСЯЦ` | 1 month | 32,999 ₽ | Detail page not opened | [Listing](https://ggsel.net/catalog/product/avto-claude-ai-fable-5-5-max-20x-podpiska-ai-1-mesiac-102501829) |
| GGSEL | `102367354` | `Claude Max 20X 1M: Opus 5.5, Fable 5.1, Code/Cowork | F.A.S.T, FULL WARRANTY` | 1 month | 72,999 ₽ | Detail page not opened | [Listing](https://ggsel.net/catalog/product/claude-max-20x-1m-opus-5-5-fable-5-1-code-cowork-f-a-s-t-full-warranty-102367354) |
| GGSEL | `102445271` | `CLAUDE AI PRO max 5 НА 1 МЕСЯЦ!` | 1 month | 15,190 ₽ | Detail page not opened | [Listing](https://ggsel.net/catalog/product/claude-ai-pro-max-5-na-1-mesiac-102445271) |

These examples demonstrate category coverage and price presentation only. They are not a ranked recommendation, seller-quality check, purchase recommendation, or live price verification on the item detail page.

## Repeatable benchmark protocol

For a future comparison, use the `repeat_run_template` in `docs/audits/data/2026-10-23-marketplace-discovery-benchmark.json`. Record one row for each marketplace, query or category route. On each run:

1. Record the date, host, isolated headless session, marketplace, and exact entry URL.
2. Use the visible search field and record each exact query, whether the page navigated, and the visible suggestions/results.
3. Open the public service/tier categories through visible category links. Count distinct listing IDs/URLs in the rendered offer collection; do not count repeated card-image, title, and buy anchors as separate offers.
4. Record whether pagination or “Показать ещё” is present. If present, record the count before and after one click. If it does not change, mark the sample unexhausted and do not infer a total.
5. Open selected listing detail pages without entering checkout. Record title, term, and detail-page price separately from the category-card price.
6. Compare unique listing URLs with the current catalogue snapshot, keeping normalized option rows and unique listings as separate counts.
7. Preserve exact IDs and URLs for matches; record 403, empty search UI, hydration changes, and inaccessible pages as blockers or coverage limits.

## Limitations

- Plati is wholly unverified in this pass due to 403 on server-44 and server-88.
- GGSEL homepage search did not expose query-specific suggestions/results for the tested MiniMax aliases.
- The general Claude category's show-more button did not advance after repeated clicks. The Pro category showed 60 unique listing URLs and a show-more button that was not clicked; neither category is exhausted.
- Category membership is a discovery signal, not proof that every card is a valid subscription of the named tier. Some cross-sell or miscategorized cards can occur.
- The only item detail price check found no numeric price. All listed ruble prices are explicitly category-card observations.
- Counts are date- and session-bounded UI snapshots, not total current offer counts.
