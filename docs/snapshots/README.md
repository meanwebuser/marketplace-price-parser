# Snapshots

Each dated file is a real marketplace scan or curated gift-list snapshot.
Scanner snapshots come from `cli.py --family <name>` against live marketplace
data. Gift-list snapshots combine the final-verified offers with a small number
of explicitly labelled manual marketplace checks. Files are committed so
reviewers can audit dates, prices, offer links, and delivery conditions.

Naming: `YYYY-MM-DD-<family>.md` and matching CSV/raw evidence in `data/`.
Families include `minimax`, `chatgpt`, `kimi`, `zai`, and the combined `birthday`
wishlist. The wishlist is grouped by service and gift tier, not by price rank.

A scanner snapshot includes, where available:
- run timestamp and raw-data SHA-256 (truncated) for reproducibility;
- the canonical command line used;
- verification summary at the time of the run;
- cheapest-per-(tier, duration, delivery) table with full URLs;
- links to listings a human can verify in a browser.

The birthday wishlist adds a per-person estimate for an entered number of
contributors. It uses equal shares before payment fees; it does not place an
order or collect contributions.

If a snapshot is wrong, do not edit it — add a new dated file that
supersedes it and link to the corrected one. Snapshots are immutable
historical evidence.
