from types import SimpleNamespace

import pytest

from scanner import proxy_source


def test_parse_proxy_list_deduplicates_and_ignores_blank_or_comment_lines():
    assert proxy_source.parse_proxy_list(
        "\n# local pool\nhttp://proxy-a.example:8085\n"
        "http://proxy-a.example:8085\nhttps://user:pass@proxy-b.example:443\n"
    ) == [
        "http://proxy-a.example:8085",
        "https://user:pass@proxy-b.example:443",
    ]


@pytest.mark.parametrize(
    "entry",
    [
        "socks5://proxy.example:1080",
        "http://proxy.example",
        "http://proxy.example:not-a-port",
        "http://proxy.example:8080/path",
        "http://proxy.example:8080/?token=secret",
    ],
)
def test_parse_proxy_list_rejects_non_http_or_ambiguous_entries(entry):
    with pytest.raises(proxy_source.ProxySourceError):
        proxy_source.parse_proxy_list(entry)


def test_fetch_proxy_urls_returns_empty_when_source_is_not_configured(monkeypatch):
    monkeypatch.delenv("MARKETPLACE_PROXY_SOURCE_URL", raising=False)
    monkeypatch.delenv("MARKETPLACE_PROXY_URL", raising=False)
    assert proxy_source.fetch_proxy_urls() == []


def test_fetch_proxy_urls_accepts_one_rotating_http_proxy_from_runtime_config(monkeypatch):
    monkeypatch.delenv("MARKETPLACE_PROXY_SOURCE_URL", raising=False)
    monkeypatch.setenv("MARKETPLACE_PROXY_URL", "http://127.0.0.1:18190")
    assert proxy_source.fetch_proxy_urls() == ["http://127.0.0.1:18190"]


def test_fetch_proxy_urls_uses_curl_stdin_config_without_printing_addresses(monkeypatch):
    endpoint = "http://127.0.0.1:18082/list"
    token = "proxy-list-secret"
    monkeypatch.setattr(proxy_source.shutil, "which", lambda _: "/usr/bin/curl")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="http://proxy-a.example:8085\nhttp://proxy-b.example:8085\n",
            stderr="",
        )

    monkeypatch.setattr(proxy_source.subprocess, "run", fake_run)
    result = proxy_source.fetch_proxy_urls(endpoint, bearer_token=token)
    assert result == [
        "http://proxy-a.example:8085",
        "http://proxy-b.example:8085",
    ]
    command, kwargs = calls[0]
    assert command == ["/usr/bin/curl", "--config", "-"]
    assert endpoint not in command and token not in command
    assert endpoint in kwargs["input"] and token in kwargs["input"]
    assert "proxy-a.example" not in kwargs["input"]


def test_playwright_proxy_options_separate_server_and_auth():
    assert proxy_source.playwright_proxy_options(
        "http://user%40name:p%3Ass@proxy.example:8085"
    ) == {
        "server": "http://proxy.example:8085",
        "username": "user@name",
        "password": "p:ss",
    }


def test_fetch_proxy_urls_redacts_endpoint_when_curl_fails(monkeypatch):
    endpoint = "http://private.example/secret/path"
    monkeypatch.setattr(proxy_source.shutil, "which", lambda _: "/usr/bin/curl")
    monkeypatch.setattr(
        proxy_source.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=22, stdout="", stderr=endpoint),
    )
    with pytest.raises(proxy_source.ProxySourceError) as error:
        proxy_source.fetch_proxy_urls(endpoint)
    assert endpoint not in str(error.value)


def test_collector_passes_proxy_list_through_private_temp_file_and_deletes_it(monkeypatch, tmp_path):
    from scanner import collect as collect_module

    proxy_urls = ["http://user:secret@proxy.example:8085"]
    output_path = tmp_path / "raw.json"
    seen = {}

    def fake_popen(command, **kwargs):
        import io
        option_index = command.index("--proxy-list-file")
        proxy_file = __import__("pathlib").Path(command[option_index + 1])
        seen["mode"] = proxy_file.stat().st_mode & 0o777
        seen["payload"] = proxy_file.read_text(encoding="utf-8")
        seen["path"] = proxy_file
        out_path = __import__("pathlib").Path(command[command.index("--out") + 1])
        out_path.write_text('{"listings": []}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=io.StringIO(""), wait=lambda: 0)

    monkeypatch.setattr(collect_module.subprocess, "Popen", fake_popen)
    from scanner import plati_http

    async def fake_plati(candidates, *, workers, proxy_urls):
        assert workers == 10
        return [], candidates, {"pageRequests": 0, "optionRequests": 0,
                                "priceOptions": 0, "failedOptions": 0}

    monkeypatch.setattr(plati_http, "collect_plati_http", fake_plati)
    result = collect_module.collect(
        [{"source": "plati", "native_id": "1"}], output_path,
        workers=1, http_workers=10, headless=True, proxy_urls=proxy_urls
    )
    assert result["listings"] == []
    assert result["config"]["httpWorkers"] == 10
    assert result["config"]["browserWorkers"] == 1
    assert seen["mode"] == 0o600
    assert "secret" in seen["payload"]
    assert not seen["path"].exists()


def test_plati_discovery_rotates_configured_proxy_urls_without_logging_them(monkeypatch):
    import json
    from scanner import discover

    used_proxies = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "content": {"items": [{
                    "name": [{"locale": "ru-RU", "value": "test offer"}],
                    "product_id": "42", "price": 100,
                    "name_url": "test-offer", "seller_name": "seller",
                }]}
            }).encode()

    class Opener:
        def __init__(self, proxy):
            self.proxy = proxy

        def open(self, _request, timeout):
            assert timeout == 30
            used_proxies.append(self.proxy)
            return Response()

    proxies = ["http://proxy-a.example:8085", "http://proxy-b.example:8085"]
    monkeypatch.setattr(discover, "_candidate_matches_family", lambda _label, _family: True)
    monkeypatch.setattr(
        discover,
        "build_opener",
        lambda handler: Opener(handler.proxies["https"]),
    )
    family = type("Family", (), {"name": "sample", "search_terms": ("one", "two")})()
    errors = []
    candidates, transport = discover.discover_plati(
        family, query_errors=errors, proxy_urls=proxies
    )
    assert transport == "urllib-proxy"
    assert [item["native_id"] for item in candidates] == ["42"]
    assert set(used_proxies) == set(proxies)
    assert errors == []
