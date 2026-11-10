"""The appliance state DB keeps large byte values (S3 object bodies…) out of the signed state
JSON, in content-addressed files beside it — and still round-trips, dedupes, survives
snapshots, garbage-collects and stays tamper-evident.

    python3 tests/conformance/test_state_blob_store.py
"""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.vyomi_platform import SQLiteStateStore  # noqa: E402

failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else '  ' + str(extra)[:300]}")
    failed = failed or not ok


with tempfile.TemporaryDirectory() as d:
    db = Path(d) / "state.sqlite3"
    blobs = db.with_name(db.name + ".blobs")
    st = SQLiteStateStore(db)
    big, small = os.urandom(3 * 1024 * 1024), b"tiny"
    state = {"s3": {"objects": {"b": {"k": {"data": big, "versions": [{"data": big}]}, "s": {"data": small}}}}}
    t0 = time.time()
    st.save_state(state)
    raw = sqlite3.connect(db).execute("SELECT value FROM metadata WHERE key='state_json'").fetchone()[0]
    check("a 3 MB value is not inlined in the state JSON", len(raw) < 10_000, len(raw))
    check("the same bytes twice are stored once", len(os.listdir(blobs)) == 1, os.listdir(blobs))
    check("save stays fast", time.time() - t0 < 2, time.time() - t0)

    got = SQLiteStateStore(db).load_state(dict)
    o = got["s3"]["objects"]["b"]
    check("large bytes round-trip", o["k"]["data"] == big and o["k"]["versions"][0]["data"] == big)
    check("small bytes stay inline and round-trip", o["s"]["data"] == small)

    st = SQLiteStateStore(db)
    got = st.load_state(dict)
    sid = st.save_snapshot("before-delete", got, "now")
    del got["s3"]["objects"]["b"]["k"]
    st.save_state(got)
    check("a blob a snapshot still references is kept", len(os.listdir(blobs)) == 1)
    check("the snapshot restores the bytes", st.restore_snapshot(sid)["s3"]["objects"]["b"]["k"]["data"] == big)
    with sqlite3.connect(db) as c:
        c.execute("DELETE FROM snapshots")
    got["n"] = 1
    st.save_state(got)
    check("an unreferenced blob is deleted", os.listdir(blobs) == [], os.listdir(blobs))

    got["s3"]["objects"]["b"]["z"] = {"data": big}
    st.save_state(got)
    (blobs / os.listdir(blobs)[0]).write_bytes(b"forged")
    check("an altered blob is not trusted", SQLiteStateStore(db).load_state(dict)["s3"]["objects"]["b"]["z"]["data"] == b"")

sys.exit(1 if failed else 0)
