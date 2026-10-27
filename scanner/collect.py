"""Hybrid SSR HTTP and browser fallback collection for marketplace listings."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

from scanner.proxy_source import redact_proxy_details

ROOT = Path(__file__).resolve().parents[1]
CLICK_JS = ROOT / "click.py"


def collect(
    candidates: Sequence[dict] | None = None,
    out_path: Path | None = None,
    *,
    workers: int = 2,
    http_workers: int = 10,
    capture_retries: int = 2,
    headless: bool = False,
    plati_pids: Sequence[int | str] | None = None,
    ggsel_ids: Sequence[str] | None = None,
    proxy_urls: Sequence[str] | None = None,
) -> dict:
    """Collect supported GGSEL pages via SSR HTTP, with Playwright fallback.

    ``workers`` keeps the browser pool within its reviewed budget;
    ``http_workers`` controls the separate Impit/curl_cffi pool.
    """
    if out_path is None:
        raise ValueError("out_path is required")
    plati = list(plati_pids or [])
    ggsel = list(ggsel_ids or [])
    if candidates:
        for c in candidates:
            if c.get("source") == "plati" and c.get("native_id"):
                plati.append(str(c["native_id"]))
            elif c.get("source") == "ggsel" and c.get("native_id"):
                ggsel.append(c["native_id"])
    # Dedupe while preserving order
    seen = set()
    plati_unique = []
    for p in plati:
        if p not in seen:
            seen.add(p)
            plati_unique.append(p)
    seen = set()
    ggsel_unique = []
    for g in ggsel:
        if g not in seen:
            seen.add(g)
            ggsel_unique.append(g)

    urls = list(proxy_urls or [])
    fast_listings: list[dict] = []
    browser_plati = plati_unique
    browser_ggsel = ggsel_unique
    transport_counts = {"plati_http": 0, "impit": 0, "curl_cffi": 0,
                        "plati_browser_fallback": 0, "browser_fallback": 0}
    if plati_unique:
        original = {str(c.get("native_id")): c for c in (candidates or [])
                    if c.get("source") == "plati" and c.get("native_id")}
        http_candidates = [original.get(str(pid), {
            "source": "plati", "native_id": str(pid), "url": f"https://plati.market/itm/{pid}"
        }) for pid in plati_unique]
        try:
            import asyncio
            from scanner.plati_http import collect_plati_http
            plati_fast, plati_fallback, plati_counts = asyncio.run(
                collect_plati_http(http_candidates, workers=http_workers, proxy_urls=urls)
            )
            fast_listings.extend(plati_fast)
            browser_plati = [str(item.get("native_id")) for item in plati_fallback]
            transport_counts["plati_http"] = len(plati_fast)
            transport_counts["plati_browser_fallback"] = len(browser_plati)
            transport_counts.update({f"plati_{key}": value for key, value in plati_counts.items()})
        except Exception as error:
            browser_plati = plati_unique
            transport_counts["plati_browser_fallback"] = len(browser_plati)
            transport_counts["plati_http_error"] = type(error).__name__
    if ggsel_unique:
        original = {str(c.get("native_id")): c for c in (candidates or [])
                    if c.get("source") == "ggsel" and c.get("native_id")}
        http_candidates = [original.get(str(g), {"source": "ggsel", "native_id": str(g),
                                                 "url": f"https://ggsel.net/catalog/product/{g}"})
                           for g in ggsel_unique]
        try:
            import asyncio
            from scanner.ggsel_ssr import collect_ggsel_ssr
            ggsel_fast, fallback, ggsel_counts = asyncio.run(
                collect_ggsel_ssr(http_candidates, workers=http_workers, proxy_urls=urls)
            )
            fast_listings.extend(ggsel_fast)
            browser_ggsel = [str(item.get("native_id")) for item in fallback]
            transport_counts.update(ggsel_counts)
        except Exception as error:
            transport_counts["browser_fallback"] = len(ggsel_unique)
            transport_counts["ggsel_http_error"] = type(error).__name__
    cmd = ["node", str(CLICK_JS), "--workers", str(workers), "--out", str(out_path)]
    cmd.extend(["--capture-retries", str(capture_retries)])
    if headless:
        cmd.append("--headless")
    if browser_plati:
        cmd.extend(["--plati-pids", ",".join(browser_plati)])
    if browser_ggsel:
        cmd.extend(["--ggsel-ids", ",".join(browser_ggsel)])
    proxy_file: str | None = None
    browser_candidates = bool(browser_plati or browser_ggsel)
    if urls and browser_candidates:
        fd, proxy_file = tempfile.mkstemp(prefix="marketplace-proxies-", suffix=".json")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(urls, stream, ensure_ascii=False)
            cmd.extend(["--proxy-list-file", proxy_file])
            # A single configured rotating proxy can multiplex requests; a
            # list endpoint still leases each proxy to one active browser job.
            direct_rotator = (
                len(urls) == 1
                and bool(os.environ.get("MARKETPLACE_PROXY_URL", "").strip())
                and not bool(os.environ.get("MARKETPLACE_PROXY_SOURCE_URL", "").strip())
            )
            if direct_rotator:
                cmd.append("--proxy-reuse")
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=ROOT,
            )
            streamed = []
            assert proc.stdout is not None
            for line in proc.stdout:
                safe_line = redact_proxy_details(line, urls)
                streamed.append(safe_line)
                print(safe_line, end="", flush=True)
            proc.wait()
            proc = SimpleNamespace(returncode=proc.returncode,
                                   stdout="".join(streamed), stderr="")
        finally:
            try:
                Path(proxy_file).unlink(missing_ok=True)
            except OSError:
                pass
    elif browser_candidates:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    else:
        proc = None
    if proc is not None and proc.returncode != 0:
        details = redact_proxy_details(proc.stderr or proc.stdout, urls)
        raise RuntimeError(f"click.py failed: {details}")
    if proc is not None:
        raw = json.loads(Path(out_path).read_text())
    else:
        raw = {"schemaVersion": 2, "startedAt": datetime.now(timezone.utc).isoformat(),
               "config": {"workers": workers, "headless": headless}, "listings": []}
    raw["listings"] = [*fast_listings, *raw.get("listings", [])]
    raw.setdefault("config", {})
    raw["config"].update({"httpWorkers": max(1, min(int(http_workers), 10)),
                          "browserWorkers": workers,
                          "httpPlatiIds": [str(item.get("pid")) for item in fast_listings if item.get("marketplace") == "plati"],
                          "httpGGSELIds": [str(item.get("pid")) for item in fast_listings if item.get("marketplace") == "ggsel"],
                          "httpFallbackPlatiIds": browser_plati,
                          "httpFallbackGGSELIds": browser_ggsel,
                          "transportCounts": transport_counts})
    raw["finishedAt"] = datetime.now(timezone.utc).isoformat()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw


if __name__ == "__main__":
    import argparse
    from scanner.discover import discover_all
    from families import FAMILY_REGISTRY
    from scanner.proxy_source import fetch_proxy_urls

    p = argparse.ArgumentParser()
    p.add_argument("--family", required=True, choices=list(FAMILY_REGISTRY))
    p.add_argument("--max", type=int, default=80)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--http-workers", type=int, default=10)
    p.add_argument("--headless", action="store_true", help="force all marketplace browsers to stay hidden")
    p.add_argument("--out", default="/tmp/raw.json")
    args = p.parse_args()

    proxy_urls = fetch_proxy_urls()
    if proxy_urls:
        print(f"proxy source: {len(proxy_urls)} HTTP proxies loaded (addresses hidden)")
    family = FAMILY_REGISTRY[args.family]
    discovery = discover_all(family, args.max, proxy_urls=proxy_urls,
                             http_workers=args.http_workers)
    print(f"discovery: plati={discovery['plati_found']}, ggsel={discovery['ggsel_found']}")
    result = collect(
        discovery["candidates"], Path(args.out), workers=args.workers,
        http_workers=args.http_workers,
        headless=args.headless, proxy_urls=proxy_urls,
    )
    print(f"collected: {len(result['listings'])} listings → {args.out}")
