"""Cloud Tasks retry/backoff semantics (engine) — the dispatcher in core/gcp_cloudtasks_delivery.py relies on these."""
from core import gcp_cloudtasks_core as ct

P = "projects/p/locations/us-central1"


def _store(rc=None):
    st = ct.CloudTasksStore()
    ct.create_queue(st, P, {"name": P + "/queues/q", "retryConfig": rc or {}})
    return st


def test_backoff_doubles_then_grows_linearly_and_caps():
    rc = {"minBackoff": "1s", "maxBackoff": "20s", "maxDoublings": 3}
    assert [ct.backoff_seconds(rc, n) for n in range(1, 8)] == [1, 2, 4, 8, 12, 16, 20]


def test_failed_attempts_retry_until_max_attempts_then_give_up():
    st = _store({"maxAttempts": 3, "minBackoff": "0.5s", "maxBackoff": "5s"})
    ct.create_task(st, P + "/queues/q", {"task": {"name": P + "/queues/q/tasks/t", "httpRequest": {"url": "http://x/"}}})
    n = P + "/queues/q/tasks/t"
    assert ct.record_attempt(st, n, 500, "boom") == ("retry", 0.5)
    assert ct.record_attempt(st, n, 503, "boom") == ("retry", 1.0)
    assert st.tasks[n]["dispatchCount"] == 2
    assert ct.record_attempt(st, n, 500, "boom") == ("dead", 0.0)
    assert n not in st.tasks


def test_success_completes_the_task():
    st = _store()
    ct.create_task(st, P + "/queues/q", {"task": {"name": P + "/queues/q/tasks/t", "httpRequest": {"url": "http://x/"}}})
    assert ct.record_attempt(st, P + "/queues/q/tasks/t", 204)[0] == "done"
    assert not st.tasks


def test_enqueuer_called_on_create():
    st, seen = _store(), []
    ct.set_enqueuer(seen.append)
    try:
        ct.create_task(st, P + "/queues/q", {"task": {"httpRequest": {"url": "http://x/"}}})
    finally:
        ct.set_enqueuer(None)
    assert len(seen) == 1 and seen[0].startswith(P + "/queues/q/tasks/")
