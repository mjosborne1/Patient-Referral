"""The app reports one version everywhere it identifies itself."""
import os
import re

import pytest

os.environ["TESTING"] = "true"

from version import __version__  # noqa: E402

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_version_is_semver():
    assert SEMVER.match(__version__)


def test_version_endpoint_reports_version_and_commit(client, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")

    body = client.get("/version").get_json()

    assert body == {"version": __version__, "commit": "abc1234"}


def test_commit_falls_back_to_render_then_unknown(client, monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "def5678")
    assert client.get("/version").get_json()["commit"] == "def5678"

    monkeypatch.delenv("RENDER_GIT_COMMIT")
    assert client.get("/version").get_json()["commit"] == "unknown"


def test_sidebar_shows_the_version_linking_to_its_release(client):
    body = client.get("/filler/imaging").get_data(as_text=True)

    assert f"v{__version__}" in body
    assert f"/releases/tag/v{__version__}" in body


def test_outbound_user_agents_carry_the_version():
    import geoscape
    import hcpd_export
    import provider_directory

    expected = f"PatientReferralApp/{__version__}"
    assert expected in hcpd_export.HcpdExportClient.USER_AGENT
    assert expected in provider_directory.USER_AGENT
    assert expected in geoscape._NOMINATIM_UA
