# LLM efficiency check — 2026-10-23

## Result

The ChatGPT automatic analyzer now uses a conservative selective LLM fallback
when an API key is configured. Explicit `--analyzer llm` remains the full-LLM
baseline. Without an API key, `auto` uses deterministic regex extraction; it
does not make unauthenticated calls. Other service families keep their existing
LLM routing behavior.

## Accuracy and request reduction

The source-backed spot-gold benchmark has 15 manually checked ChatGPT rows.
On this selected, non-representative set:

| Analyzer | Exact rows | Row recall |
|---|---:|---:|
| Rules only | 7/15 | 12/15 |
| Saved all-LLM result | 12/15 | 15/15 |
| Selective replay | 15/15 | 15/15 |

Selective replay also matched all checked tier, duration, delivery, and price
fields (15/15 each). This small spot set is not a measurement of accuracy over
the full catalogue.

Using the same archived raw listings and saved predictions, selective routing
reduced prompt batches from 124 to 81 (34.7% fewer) on the historical 130-listing
capture. On the fresh 86-listing ChatGPT capture it routed 68 listings,
reducing potential prompt batches from 86 to 68 (20.9% fewer). These are
batch-count comparisons, not live model-call or token measurements.

## Limits and reproducibility

No usable LLM API key was present during this run, so current live all-LLM and
selective model outputs could not be compared. Selective replay uses saved LLM
predictions with the current deterministic gate. A public endpoint returned
HTTP 401 during earlier investigation.

Reproduce the quality comparison with:

```sh
.venv/bin/python scripts/benchmark_analyzer_quality.py \
  --gold docs/audits/data/2026-10-22-chatgpt-spot-gold.json \
  --prediction rules=docs/audits/data/2026-08-16-audit-table.csv \
  --prediction llm=docs/audits/data/2026-08-16-audit-llm-table.csv \
  --prediction selective=.tmp/llm-efficiency/2026-08-16-selective-final.csv
.venv/bin/python scripts/replay_selective_analyzer.py \
  --raw docs/audits/data/2026-08-16-audit-raw.json \
  --llm-csv docs/audits/data/2026-08-16-audit-llm-table.csv \
  --out .tmp/llm-efficiency/2026-08-16-selective-final.csv
```

Fresh raw JSON and normalized CSV snapshots for ChatGPT, Kimi, Claude, MiniMax,
and Z.ai GLM are in `docs/snapshots/data/` dated 2026-10-23. The Kimi CSV excludes
the GLM-only option from one mixed-brand listing while retaining its Kimi option.
The existing site
catalogue is rebuilt from those CSVs by `scripts/build_pages_data.py`.


## Live acceptance correction: stale default-variant prices

The public Kimi Plus / 1 month / personal-account table exposed a 291,944 RUB
row despite the suspicious-price checkbox. Filters were correct. Raw listing
6131590 showed `selected=true` at page load, but `selectedAfter=false` and
`priceChanged=false` after its deferred click: the price still belonged to Ultra
12 months. The collector had incorrectly accepted the original selected flag.

Every DOM price now requires the live selected state. Offline analysis also
rejects explicit deselection in older captures, retaining independent base-plus-
surcharge proofs. Raw evidence is unchanged. Re-evaluation marked three CSV rows
unverified: Kimi 6131590 (291,944 RUB), Kimi 6131636 (28,389 RUB), and ChatGPT
6043279 (1,876 RUB). They are excluded from the site instead of guessing prices;
published offer counts are Kimi 92 and ChatGPT 89. Other products are unchanged.

Two focused regressions failed before the fix; the affected suite passed
140 tests after it. The existing ranking test fixture was also corrected to
include its required MiniMax product title.
