# Snapshots

Each dated file is a real scan result captured from Plati and GGSEL. CSV and raw
JSON are committed so reviewers can audit the collected listings and prices.

Naming: `YYYY-MM-DD-<family>.md` for a summary, with matching CSV and raw JSON
in `data/` when available. Supported catalogue families include MiniMax,
ChatGPT, Z.ai GLM, Kimi, and Claude.

A snapshot includes:
- run timestamps in the raw JSON;
- the reconstructed headless collection command and marketplace listing counts;
- collected listing and option evidence;
- final browser-verification results, or an explicit skipped status;
- cheapest-per-(tier, duration, delivery) table with full URLs;
- links to listings a human can verify in a browser.

If a snapshot is wrong, do not edit it — add a new dated file that
supersedes it and link to the corrected one. Snapshots are immutable
historical evidence.

The 2026-10-23 refresh supersedes the earlier five-family snapshots:

| Family | Snapshot date | Raw listings (Plati / GGSEL) | CSV rows |
|---|---:|---:|---:|
| ChatGPT | 2026-10-23 | 80 / 6 | 139 |
| Kimi | 2026-10-23 | 20 / 12 | 108 |
| Claude | 2026-10-23 | 44 / 12 | 54 |
| MiniMax | 2026-10-23 | 13 / 2 | 15 |
| Z.ai GLM | 2026-10-23 | 23 / 29 | 255 |

All five were collected headless with two workers and passed zero-knowledge
ranking validation. ChatGPT's four cheapest offers passed final browser
verification. Kimi's GGSEL category crawl returned HTTP 404; its failure is
recorded in the raw snapshot, while discovered/curated listing pages were still
collected. Final verification found live price drift on one Kimi option (1 ₽)
and one Claude option (42 ₽); the failed results are preserved in their raw
snapshots. MiniMax and Z.ai GLM winner-page verification remains skipped.
The prior 2026-10-22 ChatGPT capture remains available as historical evidence.
`scripts/build_pages_data.py` reads the newest dated CSV for each family and
rebuilds `docs/data/latest.json` for the existing site.
