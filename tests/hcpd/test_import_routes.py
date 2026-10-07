"""Behaviour of the Directory Import page and its htmx routes."""
import pytest

from hcpd_export import ExportStatus, JobRunner, JobStore
from tests.hcpd.test_job_runner import ManualThreads
from tests.hcpd.test_run_job import MANIFEST, FakeHcpd

REF_HEADERS = {"X-FHIR-Server-URL": "https://referral.test/fhir"}


@pytest.fixture
def app_runner(tmp_path):
    import os
    os.environ["TESTING"] = "true"
    from app import app
    app.config["TESTING"] = True
    hcpd = FakeHcpd([ExportStatus("complete", manifest={**MANIFEST, "output": []})])
    threads = ManualThreads()
    runner = JobRunner(JobStore(tmp_path), hcpd_factory=lambda: hcpd, start_thread=threads,
                       sleep=lambda s: None, clock=lambda: 0.0)
    app.extensions["hcpd_runner"] = runner
    with app.test_client() as client:
        yield client, runner, threads, hcpd
    app.extensions.pop("hcpd_runner", None)


def _no_hcpd_auth(monkeypatch):
    for key in ("HCPD_TOKEN_ENDPOINT", "HCPD_BEARER_TOKEN", "HCPD_BEARER_TOKEN_FILE"):
        monkeypatch.delenv(key, raising=False)


def test_page_offers_types_presets_and_warns_when_no_token_is_configured(app_runner, monkeypatch):
    client, *_ = app_runner
    _no_hcpd_auth(monkeypatch)

    body = client.get("/directory/import").get_data(as_text=True)

    assert 'hx-post="/directory/import"' in body
    assert 'value="HealthcareService"' in body and 'value="service-type"' in body
    assert "HCPD_BEARER_TOKEN_FILE" in body and "HCPD_TOKEN_ENDPOINT" in body


def test_page_warns_when_the_static_token_has_expired(app_runner, monkeypatch):
    import base64
    import json
    client, *_ = app_runner
    _no_hcpd_auth(monkeypatch)
    claims = base64.urlsafe_b64encode(json.dumps({"exp": 1789689600}).encode()).rstrip(b"=").decode()
    monkeypatch.setenv("HCPD_BEARER_TOKEN", f"h.{claims}.s")

    body = client.get("/directory/import").get_data(as_text=True)

    assert "expired" in body and "2026-09-18" in body


def test_starting_an_export_builds_linked_filters_and_queues_a_job(app_runner):
    client, runner, threads, hcpd = app_runner

    response = client.post("/directory/import", headers=REF_HEADERS, data={
        "types": ["Organization", "HealthcareService"], "preset": "service-type",
        "value": "http://snomed.info/sct|310128004", "state": "QLD"})

    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "hcpd-jobs-changed"
    [job] = runner.store.list()
    assert job["mode"] == "standard"
    filters = [p["valueString"] for p in job["parameters"]["parameter"] if p["name"] == "_typeFilter"]
    assert filters == [
        "Organization?_has:HealthcareService:organization:service-type=http://snomed.info/sct|310128004",
        "HealthcareService?service-type=http://snomed.info/sct|310128004&location.address-state=QLD"]
    threads.run_all()
    assert runner.store.get(job["id"])["status"] == "complete"


def test_advanced_mode_takes_filters_verbatim(app_runner):
    client, runner, *_ = app_runner

    client.post("/directory/import", headers=REF_HEADERS, data={
        "types": ["Organization"], "preset": "advanced",
        "filters": "Organization?name=Northside Imaging\r\n\r\n"})

    [job] = runner.store.list()
    assert [p["valueString"] for p in job["parameters"]["parameter"]
            if p["name"] == "_typeFilter"] == ["Organization?name=Northside Imaging"]


def test_invalid_request_is_explained_and_no_job_is_created(app_runner):
    client, runner, *_ = app_runner

    body = client.post("/directory/import", headers=REF_HEADERS, data={
        "types": ["Organization", "Location"], "preset": "advanced",
        "filters": "Organization?name=x"}).get_data(as_text=True)

    assert "Location has no _typeFilter" in body
    assert runner.store.list() == []


def test_jobs_list_polls_while_a_job_is_active_and_offers_cancel(app_runner):
    client, runner, *_ = app_runner
    client.post("/directory/import", headers=REF_HEADERS, data={
        "types": ["Organization"], "preset": "geographic", "value": "QLD"})
    [job] = runner.store.list()

    body = client.get("/directory/import/jobs").get_data(as_text=True)

    assert 'hx-trigger="every 5s"' in body
    assert f'hx-post="/directory/import/jobs/{job["id"]}/cancel"' in body


def test_incremental_run_uses_the_last_sync_point_of_the_same_scope(app_runner):
    client, runner, threads, _ = app_runner
    client.post("/directory/import", headers=REF_HEADERS, data={
        "types": ["Organization"], "preset": "geographic", "value": "QLD"})
    threads.run_all()
    [done] = runner.store.list()

    body = client.get("/directory/import/jobs").get_data(as_text=True)
    assert f'hx-post="/directory/import/jobs/{done["id"]}/incremental"' in body
    client.post(f"/directory/import/jobs/{done['id']}/incremental", headers=REF_HEADERS)

    newest = runner.store.list()[0]
    assert newest["mode"] == "incremental"
    assert newest["parameters"]["parameter"][-1] == {"name": "_since",
                                                     "valueInstant": MANIFEST["transactionTime"]}


def test_default_runner_is_wired_from_the_environment(tmp_path, monkeypatch):
    import os
    os.environ["TESTING"] = "true"
    from app import app
    monkeypatch.setattr(app, "instance_path", str(tmp_path))
    monkeypatch.setenv("HCPD_EXPORT_SERVER", "https://hcpd.example/fhir/")
    app.extensions.pop("hcpd_runner", None)
    app.extensions.pop("hcpd_tokens", None)
    try:
        with app.test_client() as client:
            assert client.get("/directory/import/jobs").status_code == 200
            runner = app.extensions["hcpd_runner"]
            assert runner.hcpd_factory().base_url == "https://hcpd.example/fhir"
            assert (tmp_path / "hcpd" / "jobs").is_dir()
    finally:
        app.extensions.pop("hcpd_runner", None)
        app.extensions.pop("hcpd_tokens", None)
