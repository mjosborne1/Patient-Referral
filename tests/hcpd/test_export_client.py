"""Behaviour of the HCPD $export client (kickoff, poll, download, cancel)."""
import json

import pytest

from hcpd_export import HcpdError, HcpdExportClient, build_export_parameters
from tests.hcpd.conftest import HCPD, STATUS_URL

PARAMS = build_export_parameters(["Organization"], ["Organization?address-state=QLD"])
OUTCOME = {"resourceType": "OperationOutcome",
           "issue": [{"severity": "error", "code": "invalid", "diagnostics": "bad _typeFilter"}]}


def _client():
    return HcpdExportClient(HCPD, token=lambda: "jwt-1")


def test_kickoff_posts_parameters_async_and_returns_the_status_url(http):
    http.post(f"{HCPD}/$export", status_code=202, headers={"Content-Location": STATUS_URL})

    assert _client().kickoff(PARAMS) == STATUS_URL

    sent = http.last_request
    assert sent.json() == PARAMS
    assert sent.headers["Prefer"] == "respond-async"
    assert sent.headers["Authorization"] == "Bearer jwt-1"
    assert sent.headers["Content-Type"] == "application/fhir+json"
    assert sent.headers["Accept"] == "application/fhir+json"
    assert sent.headers["X-Request-ID"]


def test_rejected_kickoff_raises_with_the_operation_outcome(http):
    http.post(f"{HCPD}/$export", status_code=400, json=OUTCOME)

    with pytest.raises(HcpdError) as error:
        _client().kickoff(PARAMS)
    assert error.value.operation_outcome == OUTCOME


def test_poll_in_progress_reports_retry_after_and_progress(http):
    http.get(STATUS_URL, status_code=202,
             headers={"Retry-After": "60", "X-Progress": "found 954 of 1,000 resources"})

    status = _client().poll(STATUS_URL)

    assert (status.state, status.retry_after, status.progress) == (
        "in-progress", 60, "found 954 of 1,000 resources")


def test_poll_complete_returns_the_manifest(http):
    manifest = {"transactionTime": "2026-02-19T10:27:53.423+11:00", "requiresAccessToken": True,
                "output": [{"type": "Organization", "url": f"{HCPD}/Binary/abc"}], "error": []}
    http.get(STATUS_URL, json=manifest)

    status = _client().poll(STATUS_URL)

    assert (status.state, status.manifest) == ("complete", manifest)


@pytest.mark.parametrize("code, state", [(400, "failed"), (404, "gone")])
def test_poll_failure_and_unknown_job(http, code, state):
    http.get(STATUS_URL, status_code=code, json=OUTCOME)

    assert _client().poll(STATUS_URL).state == state


def test_download_parses_ndjson_and_sends_the_token_only_when_required(http):
    lines = [{"resourceType": "Organization", "id": "o1"}, {"resourceType": "Organization", "id": "o2"}]
    http.get(f"{HCPD}/Binary/abc", text="\n".join(json.dumps(r) for r in lines) + "\n\n")

    assert _client().download(f"{HCPD}/Binary/abc", requires_token=False) == lines
    assert http.last_request.headers["Accept"] == "application/fhir+ndjson"
    assert "Authorization" not in http.last_request.headers

    _client().download(f"{HCPD}/Binary/abc", requires_token=True)
    assert http.last_request.headers["Authorization"] == "Bearer jwt-1"


def test_cancel_deletes_the_status_url(http):
    http.delete(STATUS_URL, status_code=202)

    _client().cancel(STATUS_URL)

    assert http.last_request.method == "DELETE"
