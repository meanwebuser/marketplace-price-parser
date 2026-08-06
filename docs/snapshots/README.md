# Snapshots

Each dated file is a real scan result, captured after running
`cli.py --family <name>` against live Plati + GGSEL data. Files are
committed so reviewers can audit historical prices and verify the
analyzer output matches what was actually for sale.

Naming: `YYYY-MM-DD-<family>.md` — one file per (date, family) run.

A snapshot includes:
- run timestamp and raw-data SHA-256 (truncated) for reproducibility;
- the canonical command line used;
- pytest summary at the time of the run;
- cheapest-per-(tier, duration, delivery) table with full URLs;
- links to listings a human can verify in a browser.

If a snapshot is wrong, do not edit it — add a new dated file that
supersedes it and link to the corrected one. Snapshots are immutable
historical evidence.
