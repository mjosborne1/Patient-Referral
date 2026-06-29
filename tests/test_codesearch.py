"""Unit tests for codesearch.py — all HTTP calls are mocked."""

import sys
import os
import threading
import time

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import codesearch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token_response(token="tok123", expires_in=300):
    m = MagicMock()
    m.ok = True
    m.json.return_value = {"access_token": token, "expires_in": expires_in}
    m.raise_for_status.return_value = None
    return m


def _make_search_response(matches):
    m = MagicMock()
    m.ok = True
    m.json.return_value = {"matches": matches}
    return m


def _reset_token_cache():
    codesearch._token = None
    codesearch._token_fetched_at = None
    codesearch._TOKEN_TTL = 270
    codesearch._warned_unconfigured = False


# ---------------------------------------------------------------------------
# search_codes — unconfigured
# ---------------------------------------------------------------------------

def test_search_codes_no_endpoint(monkeypatch):
    _reset_token_cache()
    monkeypatch.delenv("CODESEARCH_API_ENDPOINT", raising=False)
    result = codesearch.search_codes("full blood count", "some-context")
    assert result == []


# ---------------------------------------------------------------------------
# search_codes — happy path
# ---------------------------------------------------------------------------

def test_search_codes_returns_matches(monkeypatch):
    _reset_token_cache()
    monkeypatch.setenv("CODESEARCH_API_ENDPOINT", "https://example.com/api/v1/find-code")
    monkeypatch.setenv("CODESEARCH_TOKEN_ENDPOINT", "https://example.com/token")
    monkeypatch.setenv("CODESEARCH_CLIENT_ID", "cid")
    monkeypatch.setenv("CODESEARCH_CLIENT_SECRET", "csec")

    expected = [{"code": "26604007", "display": "Full blood count", "system": "http://snomed.info/sct"}]

    with patch("codesearch.requests.post") as mock_post:
        mock_post.side_effect = [
            _make_token_response(),
            _make_search_response(expected),
        ]
        result = codesearch.search_codes("full blood count", "ctx", top_n=5)

    assert result == expected
    assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# search_codes — stale token retry
# ---------------------------------------------------------------------------

def test_search_codes_retries_on_error(monkeypatch):
    _reset_token_cache()
    monkeypatch.setenv("CODESEARCH_API_ENDPOINT", "https://example.com/api/v1/find-code")
    monkeypatch.setenv("CODESEARCH_TOKEN_ENDPOINT", "https://example.com/token")
    monkeypatch.setenv("CODESEARCH_CLIENT_ID", "cid")
    monkeypatch.setenv("CODESEARCH_CLIENT_SECRET", "csec")

    bad_resp = MagicMock()
    bad_resp.ok = False
    bad_resp.status_code = 401
    bad_resp.text = "Unauthorized"

    expected = [{"code": "12345", "display": "Test"}]

    with patch("codesearch.requests.post") as mock_post:
        # token, bad search, fresh token (force), good search
        mock_post.side_effect = [
            _make_token_response("tok1"),
            bad_resp,
            _make_token_response("tok2"),
            _make_search_response(expected),
        ]
        result = codesearch.search_codes("test", "ctx")

    assert result == expected
    assert mock_post.call_count == 4


# ---------------------------------------------------------------------------
# search_codes — API returns non-dict
# ---------------------------------------------------------------------------

def test_search_codes_non_dict_response(monkeypatch):
    _reset_token_cache()
    monkeypatch.setenv("CODESEARCH_API_ENDPOINT", "https://example.com/api/v1/find-code")
    monkeypatch.setenv("CODESEARCH_TOKEN_ENDPOINT", "https://example.com/token")
    monkeypatch.setenv("CODESEARCH_CLIENT_ID", "cid")
    monkeypatch.setenv("CODESEARCH_CLIENT_SECRET", "csec")

    bad = MagicMock()
    bad.ok = True
    bad.json.return_value = []  # not a dict

    with patch("codesearch.requests.post") as mock_post:
        mock_post.side_effect = [_make_token_response(), bad]
        result = codesearch.search_codes("x", "ctx")

    assert result == []


# ---------------------------------------------------------------------------
# Token caching — second call reuses cached token
# ---------------------------------------------------------------------------

def test_token_cached_between_calls(monkeypatch):
    _reset_token_cache()
    monkeypatch.setenv("CODESEARCH_API_ENDPOINT", "https://example.com/api/v1/find-code")
    monkeypatch.setenv("CODESEARCH_TOKEN_ENDPOINT", "https://example.com/token")
    monkeypatch.setenv("CODESEARCH_CLIENT_ID", "cid")
    monkeypatch.setenv("CODESEARCH_CLIENT_SECRET", "csec")

    with patch("codesearch.requests.post") as mock_post:
        mock_post.side_effect = [
            _make_token_response(),
            _make_search_response([]),
            _make_search_response([]),  # second search — no extra token fetch
        ]
        codesearch.search_codes("a", "ctx")
        codesearch.search_codes("b", "ctx")

    # 1 token fetch + 2 search calls = 3 total
    assert mock_post.call_count == 3


# ---------------------------------------------------------------------------
# Both searches fail — returns []
# ---------------------------------------------------------------------------

def test_both_requests_fail_returns_empty(monkeypatch):
    _reset_token_cache()
    monkeypatch.setenv("CODESEARCH_API_ENDPOINT", "https://example.com/api/v1/find-code")
    monkeypatch.setenv("CODESEARCH_TOKEN_ENDPOINT", "https://example.com/token")
    monkeypatch.setenv("CODESEARCH_CLIENT_ID", "cid")
    monkeypatch.setenv("CODESEARCH_CLIENT_SECRET", "csec")

    bad = MagicMock()
    bad.ok = False
    bad.status_code = 500
    bad.text = "Server error"

    with patch("codesearch.requests.post") as mock_post:
        mock_post.side_effect = [
            _make_token_response(),
            bad,
            _make_token_response("tok2"),
            bad,
        ]
        result = codesearch.search_codes("x", "ctx")

    assert result == []
