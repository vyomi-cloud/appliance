"""v4 C0g — the offline appliance serves native GCP Pub/Sub (topics, subscriptions, publish /
pull / ack / modifyAckDeadline, snapshots + seek, schemas) through the shared core Nano uses
(core/gcp_pubsub_core.py), over ONE state shared with the classic console paths, durably.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway state file,
like tests/test_c0d_unified_engine.py.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0g-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

P = "c0g-proj"
V = f"/v1/projects/{P}"
W = f"/_wire{V}"
MOD = "routes.gcp_pubsub_unified"
ROOT = Path(__file__).resolve().parents[1]


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


class _gcp:
    """Resolve the space-scoped proxies as a GCP request would."""

    def __enter__(self):
        from core.app_context import REQUEST_PROVIDER
        self._t = REQUEST_PROVIDER.set("gcp")

    def __exit__(self, *a):
        from core.app_context import REQUEST_PROVIDER
        REQUEST_PROVIDER.reset(self._t)


def _first_route(path: str, method: str):
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "query_string": b"", "headers": []}
    for r in server.app.routes:
        m, _ = r.matches(scope)
        if m == Match.FULL:
            return r
    return None


def test_route_precedence(client):
    for path, method in (("/v1/projects/p/topics", "GET"), ("/v1/projects/p/topics/t", "PUT"),
                         ("/v1/projects/p/topics/t:publish", "POST"), ("/v1/projects/p/topics/t/subscriptions", "GET"),
                         ("/v1/projects/p/subscriptions/s:pull", "POST"),
                         ("/v1/projects/p/subscriptions/s:modifyAckDeadline", "POST"),
                         ("/v1/projects/p/snapshots/x", "PUT"), ("/v1/projects/p/schemas", "POST"),
                         ("/v1/projects/p/schemas:validate", "POST"),
                         ("/api/gcp/pubsub/v1/projects/p/topics", "POST"), ("/api/gcp/sqs/queues", "GET"),
                         ("/api/gcp/sqs/queues/q/receive", "POST"), ("/api/gcp/pubsub/schemas", "GET")):
        r = _first_route(path, method)
        assert r is not None and r.endpoint.__module__ == MOD, (path, r and r.endpoint)
    # neighbours on /v1/projects keep their handlers
    assert _first_route("/v1/projects/p/secrets", "GET").endpoint.__module__ != MOD
    assert _first_route("/v1/projects/p/databases", "GET").endpoint.__module__ != MOD


def test_topic_subscription_publish_pull_ack(client):
    t, s = _u("t"), _u("s")
    r = client.put(f"{W}/topics/{t}", json={"labels": {"env": "dev"}})
    assert r.status_code == 200 and r.json()["name"] == f"projects/{P}/topics/{t}", r.text
    assert client.put(f"{W}/topics/{t}", json={}).json()["error"]["status"] == "ALREADY_EXISTS"
    r = client.put(f"{W}/subscriptions/{s}", json={"topic": f"projects/{P}/topics/{t}", "ackDeadlineSeconds": 30})
    assert r.status_code == 200 and r.json()["ackDeadlineSeconds"] == 30, r.text
    assert f"projects/{P}/subscriptions/{s}" in client.get(f"{V}/topics/{t}/subscriptions").json()["subscriptions"]
    ids = client.post(f"{V}/topics/{t}:publish", json={"messages": [
        {"data": _b64("one"), "attributes": {"k": "v"}}, {"data": _b64("two")}]}).json()["messageIds"]
    assert len(ids) == 2 and len(set(ids)) == 2
    got = client.post(f"{W}/subscriptions/{s}:pull", json={"maxMessages": 10}).json()["receivedMessages"]
    assert [base64.b64decode(m["message"]["data"]).decode() for m in got] == ["one", "two"]
    assert got[0]["message"]["attributes"] == {"k": "v"} and got[0]["deliveryAttempt"] == 1
    # leased: nothing more until the deadline; a nack (modifyAckDeadline 0) redelivers now
    assert client.post(f"{V}/subscriptions/{s}:pull", json={"maxMessages": 10}).json() == {}
    assert client.post(f"{V}/subscriptions/{s}:modifyAckDeadline",
                       json={"ackIds": [got[1]["ackId"]], "ackDeadlineSeconds": 0}).status_code == 200
    again = client.post(f"{V}/subscriptions/{s}:pull", json={"maxMessages": 10}).json()["receivedMessages"]
    assert len(again) == 1 and again[0]["message"]["messageId"] == got[1]["message"]["messageId"]
    assert again[0]["deliveryAttempt"] == 2
    ack = client.post(f"{V}/subscriptions/{s}:acknowledge", json={"ackIds": [got[0]["ackId"], again[0]["ackId"]]})
    assert ack.status_code == 200 and ack.json() == {}
    sub = client.get(f"{V}/subscriptions/{s}").json()
    assert sub["topic"] == f"projects/{P}/topics/{t}"
    # modifyPushConfig flips delivery to push (stored, as the capability registry states)
    client.post(f"{V}/subscriptions/{s}:modifyPushConfig", json={"pushConfig": {"pushEndpoint": "https://example.test/h"}})
    assert client.get(f"{V}/subscriptions/{s}").json()["pushConfig"]["pushEndpoint"] == "https://example.test/h"
    assert client.patch(f"{V}/topics/{t}", json={"topic": {"labels": {"env": "prod"}}, "updateMask": "labels"}
                        ).json()["labels"] == {"env": "prod"}
    assert client.post(f"{V}/topics/{t}:testIamPermissions", json={"permissions": ["pubsub.topics.publish"]}
                       ).json() == {"permissions": ["pubsub.topics.publish"]}


def test_snapshot_and_seek(client):
    t, s, snap = _u("st"), _u("ss"), _u("snap")
    client.put(f"{W}/topics/{t}", json={})
    client.put(f"{W}/subscriptions/{s}", json={"topic": f"projects/{P}/topics/{t}"})
    client.post(f"{W}/topics/{t}:publish", json={"messages": [{"data": _b64("m1")}]})
    r = client.put(f"{W}/snapshots/{snap}", json={"subscription": f"projects/{P}/subscriptions/{s}"})
    assert r.status_code == 200, r.text                      # was S3 NoSuchBucket (404 XML) pre-C0g
    assert r.json()["topic"] == f"projects/{P}/topics/{t}"
    assert any(x["name"].endswith(f"/snapshots/{snap}") for x in client.get(f"{W}/snapshots").json()["snapshots"])
    assert f"projects/{P}/snapshots/{snap}" in client.get(f"{V}/topics/{t}/snapshots").json()["snapshots"]
    m = client.post(f"{V}/subscriptions/{s}:pull", json={"maxMessages": 5}).json()["receivedMessages"]
    client.post(f"{V}/subscriptions/{s}:acknowledge", json={"ackIds": [m[0]["ackId"]]})
    assert client.post(f"{V}/subscriptions/{s}:pull", json={"maxMessages": 5}).json() == {}
    assert client.post(f"{W}/subscriptions/{s}:seek", json={"snapshot": f"projects/{P}/snapshots/{snap}"}).status_code == 200
    replay = client.post(f"{V}/subscriptions/{s}:pull", json={"maxMessages": 5}).json()["receivedMessages"]
    assert [base64.b64decode(x["message"]["data"]).decode() for x in replay] == ["m1"]
    assert client.patch(f"{V}/snapshots/{snap}", json={"snapshot": {"labels": {"a": "b"}}, "updateMask": "labels"}
                        ).json()["labels"] == {"a": "b"}
    assert client.delete(f"{V}/snapshots/{snap}").status_code == 200
    assert client.get(f"{V}/snapshots/{snap}").status_code == 404


def test_schemas(client):
    sid = _u("sch")
    avro = json.dumps({"type": "record", "name": "R", "fields": [{"name": "n", "type": "int"}]})
    r = client.post(f"{W}/schemas?schemaId={sid}", json={"type": "AVRO", "definition": avro})
    assert r.status_code == 200 and r.json()["name"] == f"projects/{P}/schemas/{sid}", r.text
    assert client.get(f"{V}/schemas/{sid}?view=FULL").json()["definition"] == avro
    assert any(x["name"].endswith("/" + sid) for x in client.get(f"{V}/schemas").json()["schemas"])
    assert client.post(f"{V}/schemas:validate", json={"schema": {"type": "AVRO", "definition": avro}}).status_code == 200
    assert client.post(f"{V}/schemas:validate", json={"schema": {"type": "AVRO", "definition": "{nope"}}).status_code == 400
    ok = client.post(f"{V}/schemas:validateMessage", json={"name": sid, "encoding": "JSON", "message": _b64('{"n": 1}')})
    bad = client.post(f"{V}/schemas:validateMessage", json={"name": sid, "encoding": "JSON", "message": _b64('{"n": "x"}')})
    assert ok.status_code == 200 and bad.status_code == 400
    # a topic bound to the schema rejects a violating message on publish
    t = _u("schema-topic")
    client.put(f"{V}/topics/{t}", json={"schemaSettings": {"schema": f"projects/{P}/schemas/{sid}", "encoding": "JSON"}})
    assert client.post(f"{V}/topics/{t}:publish", json={"messages": [{"data": _b64('{"n": "x"}')}]}).status_code == 400
    assert client.delete(f"{V}/schemas/{sid}").status_code == 200
    assert client.get(f"{V}/schemas/{sid}").status_code == 404


def test_unknown_paths_are_google_errors_not_s3(client):
    for method, path in (("GET", f"{W}/topics/x/nope"), ("POST", f"{W}/subscriptions/x:bogus"),
                         ("GET", f"{W}/snapshots/missing"), ("PUT", f"{W}/schemas/a/b")):
        r = client.request(method, path, json={})
        assert r.status_code in (400, 404), (path, r.status_code, r.text)
        assert r.headers["content-type"].startswith("application/json"), (path, r.text)
        assert r.json()["error"]["status"] in ("NOT_FOUND", "INVALID_ARGUMENT"), r.text
        assert "NoSuchBucket" not in r.text


def test_classic_console_paths_share_the_core_state(client):
    t = _u("classic")
    c = "/api/gcp/pubsub/v1/projects/" + P
    r = client.post(f"{c}/topics", json={"topicId": t, "labels": {"x": "y"}})   # pre-v4 POST-with-body create
    assert r.status_code == 200, r.text
    assert client.get(f"{V}/topics/{t}").json()["labels"] == {"x": "y"}
    # …which also made the default pull subscription of the same id
    assert client.get(f"{V}/subscriptions/{t}").json()["topic"] == f"projects/{P}/topics/{t}"
    lst = client.get(f"{c}/topics").json()
    assert lst["kind"] == "pubsub#topicList" and any(x["name"].endswith("/" + t) for x in lst["topics"])
    client.post(f"{V}/topics/{t}:publish", json={"messages": [{"data": _b64("hello")}]})
    peek = client.get(f"{V}/subscriptions/{t}/messages").json()["receivedMessages"]   # non-native peek
    assert [base64.b64decode(x["message"]["data"]).decode() for x in peek] == ["hello"]
    assert any(m["data"] == _b64("hello") for m in client.get(f"{V}/topics/{t}/messages").json()["messages"])
    got = client.post(f"/api/gcp/sqs/queues/{t}/receive?project={P}", json={}).json()["receivedMessages"]
    assert len(got) == 1
    assert client.post(f"/api/gcp/sqs/queues/{t}/messages/{got[0]['ackId']}/delete?project={P}", json={}
                       ).json() == {"acknowledged": True}
    client.post(f"{V}/topics/{t}:publish", json={"messages": [{"data": _b64("x")}]})
    assert client.post(f"{V}/subscriptions/{t}:purge").json() == {"done": True}
    assert client.get(f"{V}/subscriptions/{t}/messages").json()["receivedMessages"] == []
    # classic schemas alias
    sc = _u("csch")
    assert client.post(f"/api/gcp/pubsub/schemas?project={P}", json={"name": sc, "definition": "{}"}).status_code == 200
    assert any(x["name"].endswith("/" + sc) for x in client.get(f"{V}/schemas").json()["schemas"])
    assert client.delete(f"/api/gcp/pubsub/schemas/{sc}?project={P}").json()["deleted"] is True
    # console summary counts the project's topics from the core
    assert client.get(f"/api/gcp/console/summary?project={P}").json()["services"]["gcp-pubsub"] >= 1
    # inventory (cost savings / resource_count) reads the same records
    with _gcp():
        from core.app_context import gcp_pubsub_state
        assert f"projects/{P}/topics/{t}" in gcp_pubsub_state["topics"]
    # classic delete: {done}, and (pre-v4 contract) the topic's subscriptions go with it
    assert client.delete(f"{c}/topics/{t}").json() == {"done": True}
    assert client.get(f"{V}/topics/{t}").status_code == 404
    assert client.get(f"{V}/subscriptions/{t}").status_code == 404


def test_pre_v4_records_are_adopted(client):
    """Records the pre-v4 handlers wrote (bare-id keys + a per-subscription backlog) are
    converted in place on first use and stay deliverable."""
    t = _u("legacy")
    with _gcp():
        from core.app_context import gcp_pubsub_state
        gcp_pubsub_state.setdefault("topics", {})[t] = {"topicId": t, "project": P, "name": f"projects/{P}/topics/{t}",
                                                          "labels": {"old": "1"}, "createTime": "2026-01-01T00:00:00Z"}
        gcp_pubsub_state.setdefault("subscriptions", {})[t + "-sub"] = {
            "subscriptionId": t + "-sub", "project": P, "name": f"projects/{P}/subscriptions/{t}-sub",
            "topic": f"projects/{P}/topics/{t}", "ackDeadlineSeconds": 10}
        gcp_pubsub_state.setdefault("messages", {})[t + "-sub"] = [
            {"messageId": "m-old", "data": _b64("legacy"), "attributes": {}, "publishTime": "2026-01-01T00:00:00Z"}]
    assert client.get(f"{V}/topics/{t}").json()["labels"] == {"old": "1"}
    got = client.post(f"{V}/subscriptions/{t}-sub:pull", json={"maxMessages": 5}).json()["receivedMessages"]
    assert [x["message"]["messageId"] for x in got] == ["m-old"]
    with _gcp():
        assert t not in gcp_pubsub_state["topics"] and f"projects/{P}/topics/{t}" in gcp_pubsub_state["topics"]


def test_cloud_scheduler_pubsub_target_publishes_into_the_core(client):
    t, s = _u("sched-t"), _u("sched-s")
    client.put(f"{V}/topics/{t}", json={})
    client.put(f"{V}/subscriptions/{s}", json={"topic": f"projects/{P}/topics/{t}"})
    from routes import gcp_pubsub_unified as gps
    assert gps.publish(P, t, _b64("tick"), {"k": "v"}) == 200
    assert gps.publish(P, _u("missing"), _b64("x")) == 404
    m = client.post(f"{V}/subscriptions/{s}:pull", json={"maxMessages": 5}).json()["receivedMessages"]
    assert base64.b64decode(m[0]["message"]["data"]) == b"tick" and m[0]["message"]["attributes"] == {"k": "v"}


def _state_slot() -> dict:
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    out = {"topics": {}, "subscriptions": {}, "snapshots": {}, "schemas": {}}
    for sp in (state.get("spaces") or {}).get("spaces", {}).values():
        slot = (sp.get("service_states") or {}).get("gcp_gcp_pubsub") or {}
        for k in out:
            out[k].update(slot.get(k) or {})
    return out


def test_state_is_durable_across_a_fresh_appliance(client):
    t, s, snap, sch = _u("dur"), _u("dursub"), _u("dursnap"), _u("dursch")
    client.put(f"{V}/topics/{t}", json={})
    client.put(f"{V}/subscriptions/{s}", json={"topic": f"projects/{P}/topics/{t}"})
    client.post(f"{V}/topics/{t}:publish", json={"messages": [{"data": _b64("survives")}]})
    client.put(f"{V}/snapshots/{snap}", json={"subscription": f"projects/{P}/subscriptions/{s}"})
    client.post(f"{V}/schemas?schemaId={sch}", json={"type": "AVRO", "definition": "{}"})
    slot = _state_slot()
    assert f"projects/{P}/topics/{t}" in slot["topics"]
    assert slot["subscriptions"][f"projects/{P}/subscriptions/{s}"]["messages"][0]["data"] == _b64("survives")
    assert f"projects/{P}/snapshots/{snap}" in slot["snapshots"]
    assert f"projects/{P}/schemas/{sch}" in slot["schemas"]
    # a brand-new appliance process on the same state file serves them natively
    code = ("import base64, json\nfrom fastapi.testclient import TestClient\nimport server\n"
            "with TestClient(server.app) as c:\n"
            f"    t = c.get('{V}/topics/{t}').status_code\n"
            f"    snaps = [x['name'] for x in c.get('/_wire{V}/snapshots').json().get('snapshots', [])]\n"
            f"    sch = c.get('{V}/schemas/{sch}').status_code\n"
            f"    m = c.post('{V}/subscriptions/{s}:pull', json={{'maxMessages': 5}}).json().get('receivedMessages', [])\n"
            "    print('RESULT', json.dumps({'t': t, 'snaps': snaps, 'sch': sch,"
            " 'data': [base64.b64decode(x['message']['data']).decode() for x in m]}))\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300, cwd=str(ROOT))
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, out.stdout[-2000:] + out.stderr[-2000:]
    res = json.loads(line[len("RESULT "):])
    assert res["t"] == 200 and res["sch"] == 200, res
    assert f"projects/{P}/snapshots/{snap}" in res["snaps"], res
    assert res["data"] == ["survives"], res


def test_legacy_opt_out_restores_the_pre_v4_handlers(monkeypatch):
    from core import wire_ingress
    from fastapi import FastAPI
    from routes import gcp_pubsub_unified as gps
    for env in ({"VYOMI_UNIFIED_INGRESS_SERVICES": "s3,dynamodb,gcs"}, {"VYOMI_LEGACY_WIRE": "1"}):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert not wire_ingress.is_unified("gcp_pubsub")
        assert gps.register(FastAPI()) == []
        assert gps.summary_counts("p") == {}
        for k in env:
            monkeypatch.delenv(k)
    assert gps.register(FastAPI()) == ["gcp_pubsub"]
    # a whole appliance booted opted out serves the pre-v4 handlers on these paths
    code = ("import server\nfrom starlette.routing import Match\n"
            "def first(p, m):\n"
            "    sc={'type':'http','path':p,'method':m,'root_path':'','query_string':b'','headers':[]}\n"
            "    return next(r for r in server.app.routes if r.matches(sc)[0]==Match.FULL)\n"
            "print(first('/v1/projects/p/topics/t','PUT').endpoint.__module__,"
            "first('/api/gcp/pubsub/v1/projects/p/topics','GET').endpoint.__module__)\n")
    env = dict(os.environ, VYOMI_LEGACY_WIRE="1", PYTHONDONTWRITEBYTECODE="1",
               CLOUDLEARN_STATE_FILE=str(_TEST_DIR / "optout.sqlite3"),
               CLOUDLEARN_LEGACY_STATE_FILE=str(_TEST_DIR / "optout.pkl"))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=300, cwd=str(ROOT))
    mods = out.stdout.strip().splitlines()[-1].split()
    assert MOD not in " ".join(mods), out.stdout + out.stderr
    assert all(m.startswith("providers.") for m in mods), mods
