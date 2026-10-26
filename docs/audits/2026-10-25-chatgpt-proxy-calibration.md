# ChatGPT parser calibration through the configured proxy source

Date: 2026-10-25

## Capture and resource use

The headless calibration capture contains 16 listing pages (8 Plati and 8 GGSEL) and 22 normalized offers. It was collected through the generic configured HTTP proxy interface with two workers. The completed canary took 106.5 seconds, peaked at 2.12 GiB RSS across 14 child processes and 2.17 CPU cores, and showed no swap increase. These observations remain within the repository's existing two-worker browser cap.

The raw capture and normalized CSV are preserved in `docs/snapshots/targeted/2026-10-25-chatgpt-proxy-calibration.raw.json` and `docs/snapshots/targeted/2026-10-25-chatgpt-proxy-calibration.csv`. The proxy source URL and returned proxy values were not persisted in the capture.

## Analyzer comparison

No `LLM_API_KEY` was configured, so no analyzer API call was made. For the requested first-pass comparison, the worker model produced a one-time, explicitly labeled annotation from the captured marketplace evidence. It is not an API analyzer result and is not an independent human gold set. The eight checked rows cover selected Plati term variants, shared and new account options, a GGSEL ready account, and token-based own-account renewals.

The existing benchmark compared that source-backed annotation and the deterministic regex replay on the same captured corpus:

| Prediction | Rows found | Exact rows | Tier | Duration | Delivery | Price |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Worker-model annotation | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |
| Deterministic regex | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |

The comparison surfaced a useful boundary: `Совместный` is explicit shared-account evidence, while `Индивидуальная` alone does not prove account ownership. The deterministic rule now marks the former as `shared_account` and leaves the latter `unknown`. The captured rows and machine-readable benchmark/gold artifacts are in `docs/audits/data/2026-10-25-chatgpt-proxy-worker-model-gold.json`, `docs/audits/data/2026-10-25-chatgpt-proxy-worker-model.csv`, and `docs/audits/data/2026-10-25-chatgpt-proxy-calibration-benchmark.json`.

This 8-row spot check supports deterministic parsing for these observed cases only. It does not establish accuracy over all sellers or offers. Routine `auto` analysis is now deterministic; use LLM analysis only for an explicitly requested calibration or a supported uncertainty-gated pass.
