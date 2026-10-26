# Configured proxy import and analyzer calibration

This reference is for the public `low_price` scanner. It describes an interface, not a particular proxy service. Keep all personal endpoints, hostnames, ports, proxy URLs, usernames, passwords, and tokens in local runtime configuration only.

## HTTP proxy-list interface

Set `MARKETPLACE_PROXY_SOURCE_URL` in the local process environment to the user-configured HTTP(S) URL that returns the list. If that endpoint requires bearer authentication, set `MARKETPLACE_PROXY_SOURCE_TOKEN` separately; do not add credentials to the URL.

The endpoint body is UTF-8 `text/plain`, with one HTTP or HTTPS proxy URL per non-empty line. Blank lines and lines beginning with `#` are ignored. Example format using reserved documentation-only hostnames:

```text
http://proxy-a.example:8085
http://user:password@proxy-b.example:8085
```

The scanner fetches the list using `curl`, validates every row, and keeps the list only in memory plus a short-lived mode-0600 file passed to the browser collector. It deletes that file after collection. Logs, raw captures, CSVs, site JSON, and command history must not contain proxy URLs or credentials. Scan provenance may record only `proxyMode` and `proxyCount`.

When the environment variable is absent, requests use the existing direct path. When it is present but the request fails or the response is invalid or empty, the scan fails explicitly rather than silently switching to direct access.

Use only a proxy service you are authorized to access. A user who reaches a private service through a local tunnel should configure the forwarded local URL in their shell or private environment file; do not commit that value. The project browser budget remains at most 2 concurrent workers even if the endpoint returns a much larger pool. The collector rotates proxy URLs across listing pages and prevents the same configured proxy from serving more than one active listing job at a time.

## LLM calibration, then deterministic replay

LLM output is a prediction to compare, not the source of truth. A source-backed gold set must come from captured marketplace evidence and selected-option checks. If a usable `LLM_API_KEY` is already present, a first calibration can compare the LLM and deterministic analyzers on identical raw input:

```sh
mkdir -p .tmp/calibration

# Collect one bounded representative sample. This writes the immutable listing evidence.
PYTHONPATH=. .venv/bin/python cli.py \
  --family chatgpt --max 8 --workers 2 --headless --analyzer regex \
  --raw .tmp/calibration/captured.json \
  --csv .tmp/calibration/collection.csv \
  --md .tmp/calibration/collection.md

# Give both analyzers a byte-identical copy of the raw listing corpus.
cp .tmp/calibration/captured.json .tmp/calibration/llm.raw.json
cp .tmp/calibration/captured.json .tmp/calibration/rules.raw.json

# Calibration prediction: this is the only all-LLM pass in the two-pass check.
PYTHONPATH=. .venv/bin/python cli.py \
  --family chatgpt --analyzer llm --skip-discover --skip-final-verify \
  --raw .tmp/calibration/llm.raw.json \
  --csv .tmp/calibration/llm.csv \
  --md .tmp/calibration/llm.md

# Deterministic prediction over the same captured listing evidence.
PYTHONPATH=. .venv/bin/python cli.py \
  --family chatgpt --analyzer regex --skip-discover --skip-final-verify \
  --raw .tmp/calibration/rules.raw.json \
  --csv .tmp/calibration/rules.csv \
  --md .tmp/calibration/rules.md

# Compare both predictions with independently checked, source-backed rows.
PYTHONPATH=. .venv/bin/python scripts/benchmark_analyzer_quality.py \
  --gold path/to/source-backed-gold.json \
  --prediction llm=.tmp/calibration/llm.csv \
  --prediction rules=.tmp/calibration/rules.csv \
  --out .tmp/calibration/quality.json
```

The gold JSON is intentionally partial and uses the existing benchmark schema: a short description plus `rows` containing the marketplace, listing ID, selected price, tier, duration, delivery, and optional source-case note. Use the browser-selected price and documented delivery evidence to resolve differences. Do not copy the LLM output into gold.

Compare `row_recall`, `exact_rows`, and each field metric on the same gold rows. If the deterministic parser misses a source-backed row or has a wrong price/tier/duration/delivery field, add a focused rule and replay both CSVs. Report the size and scope of the gold set; never call a small spot-check global accuracy.

If there is no usable LLM key, skip the LLM pass without requesting or printing a secret. Continue with deterministic replay and source-backed manual adjudication, and state that no live LLM baseline was available.

After the deterministic parser meets or exceeds the LLM prediction on the checked gold cases, use `--analyzer auto` for routine runs. `auto` is deterministic and makes no LLM calls, regardless of whether an API key is set. Use `--analyzer llm` only for an explicit calibration run; `--analyzer selective` is an explicit uncertainty-gated mode for the family that currently supports it.

For Apple gift cards, the separate prepaid parser does not assign subscription tiers or terms. Validate region, denomination currency, selected-option total, and stock state from the raw capture or headless browser. Compare its deterministic parser against a gold set of those fields instead of routing cards through the subscription LLM schema.
