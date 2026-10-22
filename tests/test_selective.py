"""Unit tests for the opt-in selective LLM routing gate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.output import offers_from_raw
from analyzer.selective import merge_selective_offers, select_uncertain_listings


def _listing(**over):
    base = {
        "marketplace": "ggsel", "pid": "123", "url": "https://example.test/p/123",
        "title": "Купить ChatGPT PRO X5 1 месяц", "pageText": "", "descText": "",
        "skippedControls": [], "options": [], "initialPrices": [], "error": None,
    }
    base.update(over)
    return base


def _option(text="Pro 1 месяц | Со входом", price=7999):
    return {
        "text": text, "clicked": True, "priceVerified": True, "priceStable": True,
        "prices": [{"text": f"{price:,}".replace(",", " ") + " ₽", "cls": "ProductBuyBlock__amount"}],
    }


def test_gate_leaves_clean_listing_out_and_ignores_generic_skipped_controls():
    clean = _listing(
        title="ChatGPT Pro подписка 1 месяц", options=[_option()],
        skippedControls=[{"kind": "button", "text": "Описание продавца"}],
    )
    raw = {"listings": [clean]}
    selected, reasons = select_uncertain_listings(raw, list(offers_from_raw(raw)))
    assert selected == []
    assert reasons == {}

    multi_plan_title = _listing(
        pid="multi-plan", title="ChatGPT Plus / Pro подписка 1 месяц",
        options=[_option("Plus 1 месяц | Со входом")],
    )
    raw = {"listings": [multi_plan_title]}
    selected, reasons = select_uncertain_listings(raw, list(offers_from_raw(raw)))
    assert selected == []
    assert reasons == {}


def test_gate_routes_missing_rows_and_only_offer_like_unparsed_options():
    missed = _listing(
        pid="missed", title="ChatGPT Plus подписка 1 месяц готовый аккаунт",
        initialPrices=[{"text": "983 ₽", "cls": "id_product_price"}],
    )
    generic_skip = _listing(
        pid="generic", title="ChatGPT Pro подписка 1 месяц", options=[_option()],
        skippedControls=[
            {"kind": "button", "text": "Описание продавца"},
            {"kind": "button", "text": "Купить сейчас за 800 ₽"},
            {"kind": "label", "text": "Да +189 ₽"},
        ],
    )
    generic_option = _listing(
        pid="quantity", title="ChatGPT Pro подписка 1 месяц",
        options=[{"kind": "select", "text": "2", "clicked": False}],
    )
    offer_skip = _listing(
        pid="variant", title="ChatGPT Plus подписка", options=[_option("Plus 1 месяц | Со входом", 2000)],
        skippedControls=[{"kind": "label", "text": "Plus 3 месяца | Со входом 5 000 ₽"}],
    )
    raw = {"listings": [missed, generic_skip, generic_option, offer_skip]}
    selected, reasons = select_uncertain_listings(raw, list(offers_from_raw(raw)))
    assert [item["pid"] for item in selected] == ["missed", "variant"]
    assert "no_deterministic_rows" in reasons[("ggsel", "missed")]
    assert "unparsed_offer_option" in reasons[("ggsel", "variant")]
    assert ("ggsel", "generic") not in reasons
    assert ("ggsel", "quantity") not in reasons


def test_gate_routes_unknown_fields_and_unstable_prices():
    listings = [
        _listing(pid="delivery", title="ChatGPT Pro подписка 1 месяц", options=[_option("Pro 1 месяц")]),
        _listing(pid="tier", title="ChatGPT подписка 1 месяц", options=[_option("1 месяц | Со входом")]),
        _listing(pid="duration", title="ChatGPT Pro подписка", options=[_option("Pro | Со входом")]),
        _listing(pid="unstable", title="ChatGPT Pro подписка 1 месяц",
                 options=[{**_option(), "priceVerified": False, "priceStable": False}]),
    ]
    raw = {"listings": listings}
    selected, reasons = select_uncertain_listings(raw, list(offers_from_raw(raw)))
    assert {item["pid"] for item in selected} == {"delivery", "tier", "duration", "unstable"}
    assert "unknown_delivery" in reasons[("ggsel", "delivery")]
    assert "unknown_tier" in reasons[("ggsel", "tier")]
    assert "unknown_duration" in reasons[("ggsel", "duration")]
    assert "unstable_price" in reasons[("ggsel", "unstable")]


def test_gate_routes_errors_and_conflicting_classification():
    failed = _listing(pid="failed", error="timeout")
    conflict = _listing(
        pid="conflict", title="ChatGPT Pro подписка 1 месяц",
        options=[_option("Plus 1 месяц | Со входом")],
    )
    raw = {"listings": [failed, conflict]}
    selected, reasons = select_uncertain_listings(raw, list(offers_from_raw(raw)))
    assert [item["pid"] for item in selected] == ["failed", "conflict"]
    assert "collector_error" in reasons[("ggsel", "failed")]
    assert "contradictory_signals" in reasons[("ggsel", "conflict")]


def test_cli_passes_only_gate_selected_listings_to_llm(monkeypatch):
    import cli
    import analyzer.llm_extract

    clean = _listing(pid="clean", title="ChatGPT Pro подписка 1 месяц", options=[_option()])
    uncertain = _listing(pid="uncertain", title="ChatGPT Pro подписка 1 месяц",
                         options=[_option("Pro 1 месяц")])
    raw = {"listings": [clean, uncertain]}
    seen = {}

    def fake_extract(subset, **kwargs):
        seen["pids"] = [item["pid"] for item in subset["listings"]]
        return [], {"called": 1, "batches": 1, "failed": 0}

    monkeypatch.setenv("LLM_API_KEY", "unit-test-key")
    monkeypatch.setattr(analyzer.llm_extract, "extract_offers", fake_extract)
    args = cli._parse_args(["--family", "chatgpt", "--analyzer", "selective"])
    family = cli._resolve_families(args)[0]
    offers, meta = cli._analyze(raw, family, args)
    assert seen["pids"] == ["uncertain"]
    assert meta["routedListings"] == 1
    assert meta["totalListings"] == 2
    assert meta["called"] == 1
    assert len(offers) == 2


def test_auto_with_key_uses_selective_gate_for_chatgpt(monkeypatch):
    import cli
    import analyzer.llm_extract

    clean = _listing(pid="clean", title="ChatGPT Pro подписка 1 месяц", options=[_option()])
    uncertain = _listing(pid="uncertain", title="ChatGPT Pro подписка 1 месяц",
                         options=[_option("Pro 1 месяц")])
    raw = {"listings": [clean, uncertain]}
    seen = []

    def fake_extract(subset, **kwargs):
        seen.extend(item["pid"] for item in subset["listings"])
        return [], {"called": 1, "batches": 1, "failed": 0}

    monkeypatch.setenv("LLM_API_KEY", "unit-test-key")
    monkeypatch.setattr(analyzer.llm_extract, "extract_offers", fake_extract)
    args = cli._parse_args(["--family", "chatgpt"])
    family = cli._resolve_families(args)[0]
    offers, meta = cli._analyze(raw, family, args)

    assert seen == ["uncertain"]
    assert meta["analyzer"] == "selective"
    assert meta["routedListings"] == 1
    assert len(offers) == 2


def test_auto_without_key_keeps_regex_and_never_calls_llm(monkeypatch):
    import cli
    import analyzer.llm_extract

    raw = {"listings": [_listing(options=[_option()])]}
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("LLM should not run without an API key")

    monkeypatch.setattr(analyzer.llm_extract, "extract_offers", unexpected_call)
    args = cli._parse_args(["--family", "chatgpt"])
    family = cli._resolve_families(args)[0]
    offers, meta = cli._analyze(raw, family, args)

    assert meta == {"analyzer": "regex"}
    assert offers


def test_auto_non_chatgpt_and_explicit_llm_keep_all_listing_mode(monkeypatch):
    import cli
    import analyzer.llm_extract

    raw = {"listings": [_listing(pid="one"), _listing(pid="two")]}
    seen = []

    def fake_extract(subset, **kwargs):
        seen.append([item["pid"] for item in subset["listings"]])
        return [], {"called": 1, "batches": 1, "failed": 0}

    monkeypatch.setenv("LLM_API_KEY", "unit-test-key")
    monkeypatch.setattr(analyzer.llm_extract, "extract_offers", fake_extract)
    for argv in (["--family", "claude"], ["--family", "chatgpt", "--analyzer", "llm"]):
        args = cli._parse_args(argv)
        family = cli._resolve_families(args)[0]
        _, meta = cli._analyze(raw, family, args)
        assert meta["analyzer"] == "llm"
    assert seen == [["one", "two"], ["one", "two"]]


def test_default_analyzer_remains_auto(monkeypatch):
    import cli

    args = cli._parse_args(["--family", "chatgpt"])
    assert args.analyzer == "auto"


def test_dry_run_report_includes_selective_routing_metric_only(capsys):
    import cli

    base = {"batches": 67, "batch_bytes": [1024]}
    cli._print_dry_run_summary(
        "chatgpt",
        {**base, "analyzer": "selective-dry", "routedListings": 70, "totalListings": 87},
    )
    selective_line = capsys.readouterr().out
    assert "67 batches, 70/87 listings routed" in selective_line

    cli._print_dry_run_summary("chatgpt", {**base, "analyzer": "llm-dry"})
    all_llm_line = capsys.readouterr().out
    assert "67 batches, total" in all_llm_line
    assert "listings routed" not in all_llm_line


def test_llm_dry_runs_write_prompts_only_to_task_local_directory(monkeypatch, tmp_path):
    import cli

    assert cli.LLM_PROMPTS_DIR == cli.ROOT / ".tmp" / "llm-efficiency" / "llm_prompts"
    raw = {
        "listings": [
            _listing(
                title="ChatGPT Pro подписка 1 месяц",
                options=[_option("Pro 1 месяц")],
            )
        ]
    }
    for analyzer in ("selective", "llm"):
        prompt_dir = tmp_path / analyzer / ".tmp" / "llm-efficiency" / "llm_prompts"
        monkeypatch.setattr(cli, "LLM_PROMPTS_DIR", prompt_dir)
        args = cli._parse_args([
            "--family", "chatgpt", "--analyzer", analyzer, "--llm-dry-run"
        ])
        family = cli._resolve_families(args)[0]
        _, meta = cli._analyze(raw, family, args)
        assert meta["batches"] == 1
        assert list(prompt_dir.glob("batch_*.json")) == [prompt_dir / "batch_00.json"]
    assert len(list(tmp_path.rglob("batch_*.json"))) == 2


def test_llm_upgrades_only_uncertain_matching_option_with_captured_price():
    listing = _listing(title="ChatGPT Pro подписка 1 месяц", options=[_option("Pro 1 месяц")])
    baseline = {
        "marketplace": "ggsel", "pid": "123", "option_text": "Pro 1 месяц",
        "raw_option_text": "Pro 1 месяц", "tier": "Pro", "duration": "1m",
        "delivery": "unknown", "price_rub": 7999, "strong_signal": True,
        "price_verified": True, "glitched": False,
    }
    candidate = {
        "marketplace": "ggsel", "pid": "123", "option_text": "Pro 1 месяц",
        "tier": "Pro", "duration": "1m", "delivery": "own_account",
        "price_rub": 7999.0, "strong_signal": True, "glitched": False,
    }
    merged = merge_selective_offers([baseline], [candidate], [listing])
    assert len(merged) == 1
    assert merged[0]["delivery"] == "own_account"
    assert merged[0]["price_verified"] is True

    bad_price = {**candidate, "price_rub": 8000.0}
    unchanged = merge_selective_offers([baseline], [bad_price], [listing])
    assert unchanged == [baseline]
