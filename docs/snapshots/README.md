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

The 2026-10-20 refresh covers MiniMax, ChatGPT, Z.ai GLM, Claude, and Kimi and
was collected headless across both marketplace discovery surfaces. The
MiniMax discovery found no GGSEL candidate matching the configured Token Plan
family, so its collected raw listings are Plati-only. Final winner verification
was explicitly skipped for MiniMax and ChatGPT; the other raw snapshots contain
browser verification results.
`scripts/build_pages_data.py` reads the newest dated CSV for each family and
rebuilds `docs/data/latest.json` for the site.
