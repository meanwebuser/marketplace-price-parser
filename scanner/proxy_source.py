"""Load an optional HTTP proxy list from a runtime-configured URL.

The public repository intentionally contains no proxy endpoint or proxy URLs.
Configure ``MARKETPLACE_PROXY_SOURCE_URL`` in the local environment. The
endpoint response is UTF-8 text with one ``http://host:port`` or
``https://host:port`` URL per non-empty line. Optional proxy user-info is
accepted, but is never logged or persisted in scan output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from urllib.parse import unquote, urlsplit


MAX_PROXY_LIST_BYTES = 1_000_000
MAX_PROXY_URLS = 4_096
DEFAULT_TIMEOUT_SECONDS = 15


class ProxySourceError(RuntimeError):
    """A configured proxy source could not be fetched or parsed safely."""


def _curl_config_quote(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ProxySourceError("proxy source config contains a newline")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _validate_source_url(source_url: str) -> None:
    try:
        parsed = urlsplit(source_url)
        _ = parsed.port
    except ValueError as error:
        raise ProxySourceError("proxy source URL is malformed") from error
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProxySourceError("proxy source URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ProxySourceError(
            "put proxy-source authentication in MARKETPLACE_PROXY_SOURCE_TOKEN, not the URL"
        )


def _validate_proxy_url(proxy_url: str, line_number: int) -> None:
    try:
        parsed = urlsplit(proxy_url)
        port = parsed.port
    except ValueError as error:
        raise ProxySourceError(f"proxy source line {line_number} has an invalid URL") from error
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not port:
        raise ProxySourceError(
            f"proxy source line {line_number} must be an HTTP(S) proxy URL with a port"
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ProxySourceError(
            f"proxy source line {line_number} must contain only a proxy URL"
        )


def playwright_proxy_options(proxy_url: str) -> dict[str, str]:
    """Convert one validated proxy URL to Playwright's context options."""
    _validate_proxy_url(proxy_url, 1)
    parsed = urlsplit(proxy_url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    options = {"server": f"{parsed.scheme}://{hostname}:{parsed.port}"}
    if parsed.username is not None:
        options["username"] = unquote(parsed.username)
    if parsed.password is not None:
        options["password"] = unquote(parsed.password)
    return options


def redact_proxy_details(message: str, proxy_urls: list[str] | tuple[str, ...]) -> str:
    """Remove configured proxy URLs and authority values from diagnostics."""
    redacted = str(message)
    for proxy_url in proxy_urls:
        try:
            parsed = urlsplit(proxy_url)
        except ValueError:
            continue
        values = [proxy_url, parsed.netloc, parsed.hostname or ""]
        if parsed.username:
            values.extend([parsed.username, unquote(parsed.username)])
        if parsed.password:
            values.extend([parsed.password, unquote(parsed.password)])
        for value in values:
            if value:
                redacted = redacted.replace(value, "[proxy]")
    return redacted


def parse_proxy_list(body: str) -> list[str]:
    """Parse the documented text format: one HTTP(S) proxy URL per line."""
    urls: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(body.splitlines(), start=1):
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        _validate_proxy_url(candidate, line_number)
        if candidate not in seen:
            urls.append(candidate)
            seen.add(candidate)
    if len(urls) > MAX_PROXY_URLS:
        raise ProxySourceError(f"proxy source returned more than {MAX_PROXY_URLS} entries")
    return urls


def fetch_proxy_urls(
    source_url: str | None = None,
    *,
    bearer_token: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch and validate proxies with curl; return an empty list if unconfigured.

    URL and optional token are supplied through runtime config and passed to
    curl via its stdin config, so neither appears in process arguments. Error
    messages intentionally omit the endpoint, response, and proxy entries.
    """
    configured_url = source_url if source_url is not None else os.environ.get(
        "MARKETPLACE_PROXY_SOURCE_URL", ""
    )
    configured_url = configured_url.strip()
    if not configured_url:
        # A single rotating HTTP proxy can also be supplied by runtime config.
        # This is useful for a local SSH forward to a managed proxy pool: each
        # HTTP CONNECT is rotated upstream, while the repository stores no
        # host, port, credentials, or proxy list.
        direct_proxy = os.environ.get("MARKETPLACE_PROXY_URL", "").strip()
        if direct_proxy:
            _validate_proxy_url(direct_proxy, 1)
            return [direct_proxy]
        return []
    _validate_source_url(configured_url)

    token = bearer_token if bearer_token is not None else os.environ.get(
        "MARKETPLACE_PROXY_SOURCE_TOKEN", ""
    )
    if token and ("\n" in token or "\r" in token):
        raise ProxySourceError("proxy-source token contains a newline")

    curl = shutil.which("curl")
    if not curl:
        raise ProxySourceError("curl is required when MARKETPLACE_PROXY_SOURCE_URL is configured")

    timeout = max(1, min(int(timeout_seconds), 60))
    config_lines = [
        f"url = {_curl_config_quote(configured_url)}",
        "fail",
        "silent",
        "show-error",
        f"max-time = {timeout}",
        f"max-filesize = {MAX_PROXY_LIST_BYTES}",
        'proto = "=http,https"',
        "max-redirs = 2",
    ]
    if token:
        config_lines.append(
            f"header = {_curl_config_quote('Authorization: Bearer ' + token)}"
        )
    try:
        result = subprocess.run(
            [curl, "--config", "-"],
            input="\n".join(config_lines) + "\n",
            capture_output=True,
            text=True,
            timeout=timeout + 2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProxySourceError("proxy source request failed or timed out") from error
    if result.returncode != 0:
        raise ProxySourceError(f"proxy source request failed (curl exit {result.returncode})")
    encoded = result.stdout.encode("utf-8")
    if len(encoded) > MAX_PROXY_LIST_BYTES:
        raise ProxySourceError("proxy source response exceeded the size limit")
    try:
        body = encoded.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ProxySourceError("proxy source response must be UTF-8 text") from error
    urls = parse_proxy_list(body)
    if not urls:
        raise ProxySourceError("configured proxy source returned no proxy URLs")
    return urls


def discovery_proxy_urls(detail_proxy_urls: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Use an optional single rotating proxy for catalog discovery.

    Some marketplace catalog APIs behave differently from product-detail and
    option-price endpoints. ``MARKETPLACE_PROXY_URL`` may point to an authorized
    rotating proxy for discovery, while ``MARKETPLACE_PROXY_SOURCE_URL`` feeds
    the larger URL list to the concurrent detail collector.
    """
    direct_proxy = os.environ.get("MARKETPLACE_PROXY_URL", "").strip()
    if direct_proxy:
        _validate_proxy_url(direct_proxy, 1)
        return [direct_proxy]
    return list(detail_proxy_urls)
