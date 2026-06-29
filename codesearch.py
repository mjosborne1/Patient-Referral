"""
CodeSearch AI client for Test Name typeahead (ServiceRequest.code).

Auth: OAuth2 client_credentials grant → Bearer token (cached, refreshed on expiry).
Search: POST to CODESEARCH_API_ENDPOINT with {text, context, top_n}.

All config is read from environment variables:
  CODESEARCH_API_ENDPOINT, CODESEARCH_TOKEN_ENDPOINT,
  CODESEARCH_CLIENT_ID, CODESEARCH_CLIENT_SECRET,
  CODESEARCH_CONTENT_TYPE  (optional, defaults to application/json)
"""

import logging
import os
import threading
import time

import requests

_token: str | None = None
_token_fetched_at: float | None = None
_TOKEN_TTL = 270  # seconds; refreshed from expires_in if provided
_token_lock = threading.Lock()

_warned_unconfigured = False


def _cfg(key: str) -> str:
    return os.environ.get(key, "").strip()


def _fetch_token() -> None:
    global _token, _token_fetched_at, _TOKEN_TTL
    token_endpoint = _cfg("CODESEARCH_TOKEN_ENDPOINT")
    client_id = _cfg("CODESEARCH_CLIENT_ID")
    client_secret = _cfg("CODESEARCH_CLIENT_SECRET")
    resp = requests.post(
        token_endpoint,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_fetched_at = time.monotonic()
    if "expires_in" in data:
        _TOKEN_TTL = max(int(data["expires_in"]) - 30, 30)


def get_token(force: bool = False) -> str:
    with _token_lock:
        if (
            force
            or _token is None
            or _token_fetched_at is None
            or (time.monotonic() - _token_fetched_at) >= _TOKEN_TTL
        ):
            _fetch_token()
        return _token  # type: ignore[return-value]


def search_codes(text: str, context: str, top_n: int = 10) -> list[dict]:
    """Return a list of {code, display, system} dicts from the CodeSearch API.

    Returns [] immediately when CODESEARCH_API_ENDPOINT is not configured.
    Retries once with a fresh token on any HTTP error.
    """
    global _warned_unconfigured
    endpoint = _cfg("CODESEARCH_API_ENDPOINT")
    if not endpoint:
        if not _warned_unconfigured:
            logging.warning(
                "CODESEARCH_API_ENDPOINT not configured — Test Name typeahead disabled"
            )
            _warned_unconfigured = True
        return []

    content_type = _cfg("CODESEARCH_CONTENT_TYPE") or "application/json"
    payload = {"text": text, "context": context, "top_n": top_n}

    def _do_request():
        token = get_token()
        return requests.post(
            endpoint,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
            timeout=10,
        )

    resp = _do_request()
    if not resp.ok:
        get_token(force=True)
        resp = _do_request()

    if not resp.ok:
        logging.error(
            "CodeSearch API error %s for query %r: %s",
            resp.status_code,
            text,
            resp.text[:200],
        )
        return []

    data = resp.json()
    return data.get("matches", []) if isinstance(data, dict) else []
