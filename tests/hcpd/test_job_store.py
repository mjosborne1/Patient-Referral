"""Persisted job and sync state under instance/hcpd."""
import pytest

from hcpd_export import JobAlreadyActive, JobStore


def test_jobs_persist_and_list_newest_first(tmp_path):
    store = JobStore(tmp_path)
    first = store.create({"mode": "standard"})
    store.save({**store.get(first["id"]), "status": "complete"})
    second = store.create({"mode": "incremental"})

    reopened = JobStore(tmp_path)
    assert [j["id"] for j in reopened.list()] == [second["id"], first["id"]]
    assert reopened.get(first["id"])["status"] == "complete"
    assert reopened.get(second["id"])["status"] == "submitted"


def test_only_one_job_may_be_active(tmp_path):
    store = JobStore(tmp_path)
    store.create({"mode": "standard"})

    with pytest.raises(JobAlreadyActive):
        store.create({"mode": "standard"})


def test_a_finished_job_frees_the_slot(tmp_path):
    store = JobStore(tmp_path)
    job = store.create({"mode": "standard"})
    store.save({**job, "status": "failed"})

    store.create({"mode": "standard"})


def test_sync_point_is_kept_per_scope(tmp_path):
    store = JobStore(tmp_path)
    store.set_since("scope-a", "2026-02-19T10:27:53.423+11:00")

    assert JobStore(tmp_path).get_since("scope-a") == "2026-02-19T10:27:53.423+11:00"
    assert JobStore(tmp_path).get_since("scope-b") is None
