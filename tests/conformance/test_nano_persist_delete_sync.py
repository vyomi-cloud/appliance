"""Nano store sync: a delete in one context (console tab / tunnel worker) must reach the others.

Each context holds a full in-memory copy and saves the whole snapshot, so a copy that keeps a
deleted key brings it back on its next save. Runs on host CPython.
"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from core import nano_persist as np
except ImportError:  # pragma: no cover - Pyodide flat layout
    import nano_persist as np  # type: ignore


def ctx(**state):
    return types.SimpleNamespace(**state)


def save(store):
    blob = json.loads(json.dumps(np.capture_store(store)))
    np.mark_saved(store)
    return blob


def test_delete_crosses_contexts_and_stays_deleted():
    console, worker = ctx(buckets={}), ctx(buckets={})
    console.buckets.update({"keep": {"n": 1}, "gone": {"n": 2}})
    np.restore_store(worker, save(console))
    assert set(worker.buckets) == {"keep", "gone"}
    del console.buckets["gone"]
    np.restore_store(worker, save(console))
    assert set(worker.buckets) == {"keep"}, "the delete must reach the other context"
    worker.buckets["from-cli"] = {"n": 3}
    np.restore_store(console, save(worker))
    assert set(console.buckets) == {"keep", "from-cli"}, "the worker's next save must not undelete it"


def test_unsaved_local_key_survives_a_restore():
    a, b = ctx(items={}), ctx(items={})
    a.items["shared"] = 1
    np.restore_store(b, save(a))
    b.items["local-unsaved"] = 2
    a.items["newer"] = 3
    np.restore_store(b, save(a))
    assert set(b.items) == {"shared", "newer", "local-unsaved"}


def test_fresh_context_keeps_its_seed_until_it_has_synced():
    seeded = ctx(items={"seed": 1})
    np.restore_store(seeded, {"state": {"items": {"other": 2}}})
    assert set(seeded.items) == {"seed", "other"}


def test_private_durable_and_non_dict_state():
    a = ctx(count=1, items={"x": 1})
    np.restore_store(a, {"state": {"count": 5, "items": {"x": 2}}})
    assert a.count == 5 and a.items == {"x": 2}
    assert "_nano_synced" not in np.capture_store(a)["state"], "bookkeeping must not enter the snapshot"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("  ok ", name)
