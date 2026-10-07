"""SIT connectathon access: a pre-generated long-lived JWT instead of OAuth client credentials."""
import base64
import json

from hcpd_export import StaticToken, jwt_expiry, token_from_env


def _jwt(payload):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256'})}.{enc(payload)}.signature"


def test_static_token_comes_from_the_environment_or_a_token_file(tmp_path, monkeypatch):
    for key in ("HCPD_TOKEN_ENDPOINT", "HCPD_BEARER_TOKEN", "HCPD_BEARER_TOKEN_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HCPD_BEARER_TOKEN", "jwt-inline")
    assert token_from_env()() == "jwt-inline"

    token_file = tmp_path / "SIT-export.txt"
    token_file.write_text("  jwt-from-file\n")
    monkeypatch.delenv("HCPD_BEARER_TOKEN")
    monkeypatch.setenv("HCPD_BEARER_TOKEN_FILE", str(token_file))
    assert token_from_env()() == "jwt-from-file"


def test_oauth_client_credentials_take_precedence_when_configured(monkeypatch):
    monkeypatch.setenv("HCPD_TOKEN_ENDPOINT", "https://auth.test/token")
    monkeypatch.setenv("HCPD_BEARER_TOKEN", "jwt-inline")

    assert not isinstance(token_from_env(), StaticToken)


def test_no_token_configured_sends_none(monkeypatch):
    for key in ("HCPD_TOKEN_ENDPOINT", "HCPD_BEARER_TOKEN", "HCPD_BEARER_TOKEN_FILE"):
        monkeypatch.delenv(key, raising=False)
    assert token_from_env()() is None


def test_expiry_is_read_from_the_jwt_without_verifying_it():
    assert jwt_expiry(_jwt({"exp": 1789689600})) == 1789689600  # 2026-09-18
    assert jwt_expiry("not-a-jwt") is None
    assert jwt_expiry(_jwt({"sub": "x"})) is None
