"""Starting, resuming and cancelling export jobs in the background."""
import pytest

from hcpd_export import ExportStatus, JobAlreadyActive, JobRunner, JobStore
from tests.hcpd.test_run_job import MANIFEST, PARAMS, FakeHcpd, FakeImporter


class ManualThreads:
    """Thread factory that records targets and runs them only when asked."""

    def __init__(self):
        self.pending = []

    def __call__(self, target):
        self.pending.append(target)
        return self

    def run_all(self):
        while self.pending:
            self.pending.pop(0)()


def _runner(tmp_path, hcpd):
    threads = ManualThreads()
    runner = JobRunner(JobStore(tmp_path), hcpd_factory=lambda: hcpd,
                       start_thread=threads, sleep=lambda s: None, clock=lambda: 0.0)
    return runner, threads


def test_started_job_runs_in_the_background_with_the_captured_importer(tmp_path):
    hcpd = FakeHcpd([ExportStatus("complete", manifest=MANIFEST)])
    importer = FakeImporter()
    runner, threads = _runner(tmp_path, hcpd)

    job = runner.start(PARAMS, mode="standard", importer=importer, source="hcpd")
    assert runner.store.get(job["id"])["status"] == "submitted"

    threads.run_all()
    assert runner.store.get(job["id"])["status"] == "complete"
    assert len(importer.applied) == 2


def test_a_second_start_while_one_is_running_is_refused(tmp_path):
    runner, _ = _runner(tmp_path, FakeHcpd([]))
    runner.start(PARAMS, mode="standard", importer=FakeImporter(), source="hcpd")

    with pytest.raises(JobAlreadyActive):
        runner.start(PARAMS, mode="standard", importer=FakeImporter(), source="hcpd")


def test_a_job_left_running_by_a_restart_is_interrupted_and_can_be_resumed(tmp_path):
    store = JobStore(tmp_path)
    job = store.save({**store.create({"mode": "standard", "parameters": PARAMS, "scope_key": "k"}),
                      "status": "polling", "status_url": "status-url"})
    hcpd = FakeHcpd([ExportStatus("complete", manifest=MANIFEST)])
    runner, threads = _runner(tmp_path, hcpd)  # a fresh process: no live threads

    assert runner.is_interrupted(runner.store.get(job["id"]))
    runner.resume(job["id"], importer=FakeImporter(), source="hcpd")
    assert not runner.is_interrupted(runner.store.get(job["id"]))
    threads.run_all()

    assert runner.store.get(job["id"])["status"] == "complete"
    assert hcpd.kicked_off_with is None  # resumed polling the existing HCPD job


def test_cancelling_an_interrupted_job_cancels_it_on_hcpd_directly(tmp_path):
    store = JobStore(tmp_path)
    job = store.save({**store.create({"mode": "standard", "parameters": PARAMS, "scope_key": "k"}),
                      "status": "polling", "status_url": "status-url"})
    hcpd = FakeHcpd([])
    runner, _ = _runner(tmp_path, hcpd)

    runner.cancel(job["id"])

    assert runner.store.get(job["id"])["status"] == "cancelled"
    assert hcpd.cancelled == ["status-url"]


def test_cancelling_a_running_job_asks_its_thread_to_stop(tmp_path):
    runner, threads = _runner(tmp_path, FakeHcpd([]))
    job = runner.start(PARAMS, mode="standard", importer=FakeImporter(), source="hcpd")

    runner.cancel(job["id"])

    assert runner.store.get(job["id"])["status"] == "cancelling"
