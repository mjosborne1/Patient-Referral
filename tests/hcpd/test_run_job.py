"""Behaviour of an export job run end to end (HCPD and referral server faked)."""
from hcpd_export import (ExportStatus, HcpdError, ImportCounts, JobStore, build_export_parameters,
                         run_job, scope_key)

PARAMS = build_export_parameters(["Organization", "Location"],
                                 ["Organization?_has:Location:organization:address-state=QLD",
                                  "Location?address-state=QLD"])
MANIFEST = {"transactionTime": "2026-10-02T09:00:00+10:00", "requiresAccessToken": True,
            "output": [{"type": "Organization", "url": "u/org"}, {"type": "Location", "url": "u/loc"}],
            "error": []}


class FakeHcpd:
    def __init__(self, statuses, files=None, kickoff_error=None):
        self.statuses = list(statuses)
        self.files = files or {"u/org": [{"resourceType": "Organization", "id": "o1"}],
                               "u/loc": [{"resourceType": "Location", "id": "l1"}]}
        self.kickoff_error = kickoff_error
        self.kicked_off_with = None
        self.cancelled = []
        self.downloads = []
        self.clock = None
        self.poll_times = []

    def kickoff(self, parameters):
        if self.kickoff_error:
            raise self.kickoff_error
        self.kicked_off_with = parameters
        return "status-url"

    def poll(self, status_url):
        self.poll_times.append(self.clock.now if self.clock else None)
        return self.statuses.pop(0)

    def download(self, url, *, requires_token):
        self.downloads.append((url, requires_token))
        return self.files[url]

    def cancel(self, status_url):
        self.cancelled.append(status_url)


class FakeImporter:
    def __init__(self, fail_type=None):
        self.applied = []
        self.fail_type = fail_type

    def apply(self, resources, *, source):
        self.applied.append(resources)
        counts = ImportCounts()
        for r in resources:
            if r["resourceType"] == self.fail_type:
                counts.add(r["resourceType"], "failed", f"{r['resourceType']}/{r['id']}: rejected")
            else:
                counts.add(r["resourceType"], "upserted")
        return counts


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _run(tmp_path, hcpd, importer=None, mode="standard", on_sleep=None):
    store = JobStore(tmp_path)
    job = store.create({"mode": mode, "parameters": PARAMS, "scope_key": scope_key(PARAMS)})
    clock = Clock()
    hcpd.clock = clock

    def sleep(seconds):
        clock.sleep(seconds)
        if on_sleep:
            on_sleep(store, job["id"])

    run_job(job["id"], store, hcpd, importer or FakeImporter(), source="hcpd",
            sleep=sleep, clock=clock.time)
    return store, store.get(job["id"]), clock


def test_successful_export_is_imported_and_advances_the_sync_point(tmp_path):
    hcpd = FakeHcpd([ExportStatus("in-progress", retry_after=60, progress="found 10 of 20"),
                     ExportStatus("complete", manifest=MANIFEST)])

    store, job, clock = _run(tmp_path, hcpd)

    assert hcpd.kicked_off_with == PARAMS
    assert job["status"] == "complete"
    assert job["counts"]["by_type"] == {"Organization": {"upserted": 1, "removed": 0, "failed": 0},
                                        "Location": {"upserted": 1, "removed": 0, "failed": 0}}
    assert hcpd.downloads == [("u/org", True), ("u/loc", True)]
    assert store.get_since(scope_key(PARAMS)) == "2026-10-02T09:00:00+10:00"


def test_polling_never_runs_faster_than_the_hcpd_rate_limit(tmp_path):
    hcpd = FakeHcpd([ExportStatus("in-progress", retry_after=30),
                     ExportStatus("in-progress", retry_after=300),
                     ExportStatus("complete", manifest=MANIFEST)])

    _run(tmp_path, hcpd)

    first, second, third = hcpd.poll_times
    assert second - first >= 120  # Retry-After 30 is raised to HCPD's 120 s limit
    assert third - second >= 300  # a longer Retry-After is honoured


def test_failed_records_complete_with_errors_and_keep_the_old_sync_point(tmp_path):
    hcpd = FakeHcpd([ExportStatus("complete", manifest=MANIFEST)])

    store, job, _ = _run(tmp_path, hcpd, importer=FakeImporter(fail_type="Location"))

    assert job["status"] == "complete-with-errors"
    assert job["counts"]["errors"] == ["Location/l1: rejected"]
    assert store.get_since(scope_key(PARAMS)) is None


def test_export_with_no_data_completes_with_the_servers_message(tmp_path):
    empty = {**MANIFEST, "output": [], "message": "Export complete, but no data"}

    store, job, _ = _run(tmp_path, FakeHcpd([ExportStatus("complete", manifest=empty)]))

    assert job["status"] == "complete"
    assert job["message"] == "Export complete, but no data"
    assert store.get_since(scope_key(PARAMS)) == MANIFEST["transactionTime"]


def test_rejected_kickoff_fails_the_job_with_the_outcome(tmp_path):
    class Rejected:
        status_code = 400
        text = ""

        def json(self):
            return {"resourceType": "OperationOutcome",
                    "issue": [{"severity": "error", "diagnostics": "bad _typeFilter"}]}

    _, job, _ = _run(tmp_path, FakeHcpd([], kickoff_error=HcpdError(Rejected())))

    assert job["status"] == "failed"
    assert "bad _typeFilter" in job["error"]


def test_server_side_failure_while_polling_fails_the_job(tmp_path):
    outcome = {"resourceType": "OperationOutcome", "issue": [{"diagnostics": "job crashed"}]}

    _, job, _ = _run(tmp_path, FakeHcpd([ExportStatus("failed", operation_outcome=outcome)]))

    assert job["status"] == "failed" and "job crashed" in job["error"]


def test_cancel_requested_while_waiting_cancels_on_hcpd(tmp_path):
    def request_cancel(store, job_id):
        store.save({**store.get(job_id), "status": "cancelling"})

    hcpd = FakeHcpd([ExportStatus("in-progress", retry_after=120)] * 3)

    _, job, _ = _run(tmp_path, hcpd, on_sleep=request_cancel)

    assert job["status"] == "cancelled"
    assert hcpd.cancelled == ["status-url"]
