"""OAuth client-credentials token for HCPD, cached until shortly before it expires."""
from hcpd_export import TokenProvider
from tests.hcpd.conftest import TOKEN_URL, FakeClock


def test_token_is_fetched_with_client_credentials_and_reused_until_near_expiry(http):
    http.post(TOKEN_URL, [{"json": {"access_token": "t1", "expires_in": 300}},
                          {"json": {"access_token": "t2", "expires_in": 300}}])
    clock = FakeClock()
    tokens = TokenProvider(TOKEN_URL, "client-a", "secret-a", scope="hcpd/export", clock=clock)

    assert tokens() == "t1"
    clock.now += 200
    assert tokens() == "t1"
    clock.now += 50  # within the 60 s expiry skew
    assert tokens() == "t2"

    form = http.request_history[0].text
    assert "grant_type=client_credentials" in form
    assert "client_id=client-a" in form and "client_secret=secret-a" in form
    assert "scope=hcpd%2Fexport" in form


def test_no_token_endpoint_means_no_token():
    assert TokenProvider(None, None, None)() is None
