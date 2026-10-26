# Headless proxy refresh results

Date: 2026-10-25. Marketplace collection used the repository's generic configured proxy source, headless Chromium and the existing two-worker cap. The configured endpoint and proxy addresses are intentionally absent from repository artifacts.

## Family snapshots

| Family | Listing pages | Recognized offers | Published rows in `latest.json` | Fresh winner checks |
| --- | ---: | ---: | ---: | ---: |
| ChatGPT | 8 | 11 | 11 | 0 winners selected for final check |
| Claude | 10 | 2 | 0 | 0 winners selected for final check |
| Kimi | 17 | 47 | 39 | 13 |
| MiniMax | 12 | 33 | 33 | 10 |
| Z.ai GLM | 19 | 116 | 117 | 9 |

Each family's raw capture, deterministic CSV and Markdown table are saved under `docs/snapshots/targeted/2026-10-25-<family>-proxy.*`. Kimi's eight rows excluded from the site fail the existing family eligibility rules. The two Claude rows were parsed as Pro+ variants, outside the supported Claude Max/Pro catalogue tiers; no Claude price is presented as a current eligible offer from this scan. Z.ai's 117th published row is the separately source-backed same-day manual GLM Max 3-month listing described in `2026-10-25-zai-max-manual-discovery.md`; its raw and CSV hashes are referenced in the proxy raw metadata.

## MiniMax selected-option discrepancy

An earlier same-day capture of GGSEL `102443754` was internally shifted: its captured option prices did not match the later independent verifier, so that run stopped and was not published as current. A fresh capture and separate headless checks of all three controls then agreed:

| Selected option | Current price | Selected and stable |
| --- | ---: | --- |
| Max, 1 month | 7,800 ₽ | yes |
| Ultra, 1 month | 12,299 ₽ | yes |
| Plus, 1 month | 2,300 ₽ | yes |

The successful option checks are preserved in the new MiniMax raw snapshot. The old failed capture remains only in the ignored local `.tmp` working area and is not part of the published snapshot.

## Calibration and resource evidence

The ChatGPT calibration corpus has 16 listing pages (8 per marketplace) and 22 collected offers. On eight source-backed annotation cases, both the one-time worker-model annotation and regex replay matched 8/8 exact rows and 32/32 checked tier, duration, delivery and price fields. No `LLM_API_KEY` was configured; the model annotation is not represented as an analyzer API run or as independent human ground truth. The deterministic shared-account rule recognizes `Совместный` and leaves `Индивидуальная` ownership unknown.

The completed two-worker canary took 106.5 seconds, peaked at 2.12 GiB RSS across 14 children and 2.17 CPU cores, and had no swap increase. The project's existing two-worker cap was kept for subsequent scans. After collection, the temporary SSH forward was closed. A check of public captures and calibration notes found no proxy endpoint, proxy address, or pool values.

`docs/data/latest.json` was rebuilt from the fresh targeted snapshots. The Apple US $50 browser proof is recorded separately in `2026-10-25-apple-us-delivery-status.md`.
