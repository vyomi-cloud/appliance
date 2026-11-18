"""GCP reference-architecture core fixes, proven with the REAL Google client libraries (REST transports, endpoint changed only).

Starts the simulator in-process (same front door the facilities app uses), then:
  1 Cloud Logging   logging.Client.list_entries(filter_='timestamp>=...', order_by=...) returns what write wrote
  2 Cloud Trace     a span written through v2 batchWrite is readable through v1 get_trace/list_traces (uint64 span ids)
  3 Cloud KMS       additional_authenticated_data is enforced on decrypt
  4 Functions       an Eventarc-triggered function that print()s runs; its output lands in Cloud Logging
  5 GCS             bucket.notification(...).create() publishes OBJECT_FINALIZE / OBJECT_DELETE into Pub/Sub (pull from the subscription)
  6 Vertex          generateContent with Tool(retrieval=Retrieval(vertex_rag_store=...)): accepted, retrieval run, groundingMetadata returned;
                    with no local model the standard 503 (never the old 400) comes back
Needs google-cloud-{logging,trace,kms,storage,pubsub,functions,aiplatform} + google-genai (see docs/architecture/v4.0/CAPABILITY-CHECK-ENV.md).
Run: PYTHONPATH=. python tests/conformance/test_gcp_ref_corefix_sdk.py [1 2 ...]   (no args = all)"""
import base64, json, os, sys, tempfile, time, uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(tempfile.mkdtemp(prefix="gcp-corefix-"), "state.sqlite3"))
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "vyomi-project")

import socket, threading
import requests
from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials, Credentials

P, LOC, TAG = "vyomi-project", "us-central1", uuid.uuid4().hex[:6]
FAILED = []


def check(name, ok, extra=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)[:400]}")
    if not ok:
        FAILED.append(name)


def start_server():
    import asyncio, anyio, uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app, router = FastAPI(), wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        body = await request.body()
        return await anyio.to_thread.run_sync(lambda: asyncio.run(wire_ingress.serve(router, request, body=body)))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"


EP = start_server()
H = {"Authorization": "Bearer vyomi-local", "Content-Type": "application/json"}


def rest(cls, **kw):
    c = cls(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=EP), **kw)
    try:
        c._transport._host = EP      # keep the http scheme for the local endpoint
    except Exception:
        pass
    return c


# ── 1 Cloud Logging ──────────────────────────────────────────────────────────────────────
def t_logging():
    from datetime import datetime, timedelta, timezone
    import google.cloud.logging as gl
    c = gl.Client(project=P, credentials=AnonymousCredentials(), _use_grpc=False, client_options=ClientOptions(api_endpoint=EP))
    c._connection.API_BASE_URL = EP
    name = f"corefix-{TAG}"
    lg = c.logger(name)
    t_before = datetime.now(timezone.utc) - timedelta(minutes=1)
    lg.log_text("first line", severity="INFO")
    time.sleep(0.01)
    lg.log_struct({"event": "second", "n": 2}, severity="ERROR")
    lg.log_text("third line", severity="WARNING")
    def L(f, **kw):   # the SDK writes one 'diagnostic' instrumentation entry with the first batch: not ours
        return [e for e in c.list_entries(filter_=f, **kw) if not (isinstance(e.payload, dict) and "logging.googleapis.com/diagnostic" in e.payload)]
    ents = L(f'logName="projects/{P}/logs/{name}"', order_by=gl.ASCENDING)
    check("list_entries by logName returns the 3 written entries in ascending order",
          len(ents) == 3 and ents[0].payload == "first line" and ents[1].payload == {"event": "second", "n": 2}, [e.payload for e in ents])
    ents = L(f'logName="projects/{P}/logs/{name}"', order_by=gl.DESCENDING)
    check("order_by=desc reverses", [e.payload for e in ents][0] == "third line", [e.payload for e in ents])
    # list_entries(): the SDK itself prepends no filter here, so also pass the explicit timestamp filters the probe used
    f_ge = f'logName="projects/{P}/logs/{name}" AND timestamp>="{t_before.strftime("%Y-%m-%dT%H:%M:%S.%f")}+0000"'
    f_z = f'logName="projects/{P}/logs/{name}" AND timestamp>="{t_before.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
    check("timestamp>= (+0000 offset form) matches", len(L(f_ge)) == 3)
    check("timestamp>= (Z form) matches", len(L(f_z)) == 3)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    check("timestamp>= a future instant matches nothing", len(L(f'logName="projects/{P}/logs/{name}" AND timestamp>="{future}"')) == 0)
    check("timestamp< a future instant matches all", len(L(f'logName="projects/{P}/logs/{name}" AND timestamp<"{future}"')) == 3)
    check("timestamp<= a past instant matches nothing", len(L(f'logName="projects/{P}/logs/{name}" AND timestamp<="2020-01-01T00:00:00Z"')) == 0)
    check("severity>=ERROR AND timestamp>= combined", len(L(f'logName="projects/{P}/logs/{name}" AND severity>=ERROR AND timestamp>="{t_before.strftime("%Y-%m-%dT%H:%M:%SZ")}"')) == 1)
    # the SDK's own default: no filter_ -> it adds a 24h timestamp filter
    got = [e for e in L(None) if e.log_name.endswith("/" + name)]
    check("list_entries() with no filter (SDK adds its own timestamp>= default) returns the entries", len(got) == 3, len(got))


# ── 2 Cloud Trace ────────────────────────────────────────────────────────────────────────
def t_trace():
    from datetime import datetime, timezone
    from google.cloud import trace_v1, trace_v2
    from google.protobuf import timestamp_pb2
    w, r = rest(trace_v2.TraceServiceClient), rest(trace_v1.TraceServiceClient)
    tid = uuid.uuid4().hex
    root, child = "aaaaaaaaaaaaaaaa", "00000000000000ff"

    def span(sid, parent, name):
        s = trace_v2.Span(name=f"projects/{P}/traces/{tid}/spans/{sid}", span_id=sid, parent_span_id=parent, display_name={"value": name})
        s.start_time = datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc); s.end_time = datetime(2026, 11, 18, 10, 0, 1, tzinfo=timezone.utc)
        return s
    w.batch_write_spans(request={"name": f"projects/{P}", "spans": [span(root, "", "agent.run"), span(child, root, "tool.call")]})
    t = r.get_trace(request={"project_id": P, "trace_id": tid})
    ids = sorted(int(s.span_id) for s in t.spans)
    check("v1 get_trace returns v2-written spans with uint64 ids", ids == sorted([int(root, 16), int(child, 16)]), ids)
    kid = next(s for s in t.spans if s.name == "tool.call")
    check("v1 parent_span_id is the parent's uint64", kid.parent_span_id == int(root, 16), kid.parent_span_id)
    lst = list(r.list_traces(request={"project_id": P, "view": trace_v1.ListTracesRequest.ViewType.COMPLETE}))
    check("v1 list_traces COMPLETE includes the trace", any(x.trace_id == tid and len(x.spans) == 2 for x in lst), [x.trace_id for x in lst])


# ── 3 Cloud KMS ──────────────────────────────────────────────────────────────────────────
def t_kms():
    from google.cloud import kms
    from google.api_core import exceptions as ex
    c = rest(kms.KeyManagementServiceClient)
    parent = f"projects/{P}/locations/{LOC}"
    ring = c.create_key_ring(request={"parent": parent, "key_ring_id": f"r{TAG}", "key_ring": {}})
    key = c.create_crypto_key(request={"parent": ring.name, "crypto_key_id": "k", "crypto_key": {"purpose": kms.CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT}})
    enc = c.encrypt(request={"name": key.name, "plaintext": b"ledger-row", "additional_authenticated_data": b"order-7"})
    ok = c.decrypt(request={"name": key.name, "ciphertext": enc.ciphertext, "additional_authenticated_data": b"order-7"})
    check("decrypt with the matching AAD returns the plaintext", ok.plaintext == b"ledger-row")
    for label, aad in (("wrong", b"order-8"), ("missing", b"")):
        try:
            c.decrypt(request={"name": key.name, "ciphertext": enc.ciphertext, "additional_authenticated_data": aad})
            check(f"decrypt with {label} AAD is refused", False, "got plaintext back")
        except ex.BadRequest as e:
            check(f"decrypt with {label} AAD is refused (400 BadRequest)", True)
    e2 = c.encrypt(request={"name": key.name, "plaintext": b"no-aad"})
    check("no-AAD ciphertext still decrypts with no AAD", c.decrypt(request={"name": key.name, "ciphertext": e2.ciphertext}).plaintext == b"no-aad")
    try:
        c.decrypt(request={"name": key.name, "ciphertext": e2.ciphertext, "additional_authenticated_data": b"x"})
        check("AAD supplied for a no-AAD ciphertext is refused", False)
    except ex.BadRequest:
        check("AAD supplied for a no-AAD ciphertext is refused", True)


# ── helpers for 4/5/6 ────────────────────────────────────────────────────────────────────
def pubsub():
    from google.cloud import pubsub_v1
    o = ClientOptions(api_endpoint=EP)
    pub = pubsub_v1.PublisherClient(credentials=AnonymousCredentials(), transport="rest", client_options=o)
    sub = pubsub_v1.SubscriberClient(credentials=AnonymousCredentials(), transport="rest", client_options=o)
    for x in (pub, sub):
        x._transport._host = EP
    return pub, sub


def gcs():
    from google.cloud import storage
    return storage.Client(project=P, credentials=AnonymousCredentials(), client_options=ClientOptions(api_endpoint=EP))


def pull(sub, name, want, tries=20):
    got = []
    for _ in range(tries):
        got += list(sub.pull(request={"subscription": name, "max_messages": 10}, timeout=20).received_messages)
        if len(got) >= want:
            break
        time.sleep(0.3)
    return got


# ── 4 event function with print ──────────────────────────────────────────────────────────
def t_eventfn():
    import io, zipfile
    from google.cloud import functions_v2 as f2
    import google.cloud.logging as gl
    b = f"evt-{TAG}"
    g = gcs(); g.create_bucket(b)
    fc = rest(f2.FunctionServiceClient)
    parent = f"projects/{P}/locations/{LOC}"
    up = fc.generate_upload_url(request={"parent": parent})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.py", "import sys, functions_framework\n\n@functions_framework.cloud_event\ndef handler(event):\n    print('ERRLINE', file=sys.stderr)\n    print('FINALIZED', event.data.get('name'), event['type'])\n    return 'ok'\n")
        z.writestr("requirements.txt", "functions-framework\n")
    requests.put(up.upload_url, data=buf.getvalue(), headers={"content-type": "application/zip"}, timeout=60).raise_for_status()
    fn = f2.Function(name=f"{parent}/functions/onfinal{TAG}", build_config=f2.BuildConfig(runtime="python312", entry_point="handler", source=f2.Source(storage_source=up.storage_source),
                                             environment_variables={"GOOGLE_FUNCTION_SIGNATURE_TYPE": "cloudevent"}),
                     service_config=f2.ServiceConfig(available_memory="256M", timeout_seconds=60))
    fc.create_function(request={"parent": parent, "function": fn, "function_id": f"onfinal{TAG}"}).result(timeout=120)
    T = f"{EP}/v1/{parent}/triggers"
    r = requests.post(T, params={"triggerId": f"fin{TAG}"}, headers=H, json={
        "eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": b}],
        "destination": {"cloudRun": {"service": f"onfinal{TAG}", "region": LOC}}})
    check("Eventarc trigger created", r.status_code in (200, 201), r.text)
    g.bucket(b).blob("sop/boiler.txt").upload_from_string(b"hello")
    d = {}
    for _ in range(30):
        d = requests.get(f"{T}/fin{TAG}/deliveries", headers=H).json()
        if d.get("delivered", 0) >= 1 or d.get("failed", 0) >= 1:
            break
        time.sleep(0.3)
    check("event delivered to the function (no print NameError)", d.get("delivered", 0) >= 1 and not d.get("retrying") and not d.get("failed"), d)
    c = gl.Client(project=P, credentials=AnonymousCredentials(), _use_grpc=False, client_options=ClientOptions(api_endpoint=EP))
    c._connection.API_BASE_URL = EP
    txt = [str(e.payload) for e in c.list_entries(filter_='stdout')]
    check("print() output appears in Cloud Logging", any("FINALIZED sop/boiler.txt google.cloud.storage.object.v1.finalized" in t for t in txt), txt[-3:])
    es = list(c.list_entries(filter_=f'logName="projects/{P}/logs/run.googleapis.com%2Fstdout" AND resource.type="cloud_run_revision"'))
    mine = [e for e in es if "FINALIZED" in str(e.payload)]
    check("stdout entry is on run.googleapis.com/stdout with cloud_run_revision service/revision labels",
          bool(mine) and mine[0].resource.labels.get("service_name") == f"onfinal{TAG}" and bool(mine[0].resource.labels.get("revision_name")), [(e.resource.type, e.resource.labels) for e in mine[:1]])
    er = list(c.list_entries(filter_=f'logName="projects/{P}/logs/run.googleapis.com%2Fstderr" AND resource.type="cloud_run_revision"'))
    check("stderr entry is on run.googleapis.com/stderr (ERROR)", any("ERRLINE" in str(e.payload) for e in er), [str(e.payload) for e in er[-2:]])


# ── 5 GCS notificationConfigs ────────────────────────────────────────────────────────────
def t_gcsnotif():
    pub, sub = pubsub()
    topic, subn = f"projects/{P}/topics/gcs-{TAG}", f"projects/{P}/subscriptions/gcs-{TAG}"
    pub.create_topic(request={"name": topic}); sub.create_subscription(request={"name": subn, "topic": topic})
    g = gcs(); b = g.create_bucket(f"notif-{TAG}")
    n = b.notification(topic_name=f"gcs-{TAG}", topic_project=P, event_types=["OBJECT_FINALIZE", "OBJECT_DELETE"], blob_name_prefix="sop/",
                       custom_attributes={"app": "facilities"}, payload_format="JSON_API_V1")
    n.create()
    check("notification created with an id and topic", bool(n.notification_id) and n.topic_name == f"gcs-{TAG}", (n.notification_id, n.topic_name))
    check("notification.exists() and list_notifications() see it", n.exists() and [x.notification_id for x in b.list_notifications()] == [n.notification_id])
    b.blob("other/ignored.txt").upload_from_string(b"x")            # outside the prefix: no message
    b.blob("sop/boiler.txt").upload_from_string(b"Boiler 30 psi")
    got = pull(sub, subn, 1)
    check("exactly one message (prefix filter honoured)", len(got) == 1, len(got))
    m = got[0].message
    a = dict(m.attributes)
    check("attributes: eventType/bucketId/objectId/payloadFormat/notificationConfig/custom",
          a.get("eventType") == "OBJECT_FINALIZE" and a.get("bucketId") == b.name and a.get("objectId") == "sop/boiler.txt"
          and a.get("payloadFormat") == "JSON_API_V1" and a.get("notificationConfig", "").endswith(f"/notificationConfigs/{n.notification_id}")
          and a.get("app") == "facilities" and a.get("objectGeneration"), a)
    body = json.loads(m.data)
    check("JSON_API_V1 payload is the object resource", body.get("name") == "sop/boiler.txt" and body.get("bucket") == b.name, body)
    sub.acknowledge(request={"subscription": subn, "ack_ids": [got[0].ack_id]})
    b.blob("sop/boiler.txt").delete()
    got = pull(sub, subn, 1)
    check("OBJECT_DELETE published on delete", got and dict(got[0].message.attributes).get("eventType") == "OBJECT_DELETE", got)
    n.delete()
    check("notification deleted", not n.exists() and list(b.list_notifications()) == [])
    sub.acknowledge(request={"subscription": subn, "ack_ids": [x.ack_id for x in got]})
    b.blob("sop/after.txt").upload_from_string(b"x")
    time.sleep(0.5)
    check("no message after the config is deleted", len(sub.pull(request={"subscription": subn, "max_messages": 5}, timeout=20).received_messages) == 0)
    from google.api_core import exceptions as ex
    try:
        b.notification(topic_name=f"missing-{TAG}", topic_project=P).create()
        check("notification to a missing topic is refused", False)
    except ex.BadRequest:
        check("notification to a missing topic is refused (400)", True)


# ── 6 generateContent with a RAG retrieval tool ──────────────────────────────────────────
DOC = ("Boiler pressure limit: the boiler must not exceed 30 psi. If pressure exceeds 30 psi, shut the burner and call the duty engineer. "
       "Chiller plant on level 3 is serviced every quarter. Elevator maintenance contract renews in March.")


def t_rag():
    from google import genai
    from google.genai import types
    from google.cloud import aiplatform_v1 as av
    from core import llm_core as llm

    class Dummy(Credentials):
        def refresh(self, request):
            self.token = "vyomi-local"
    parent = f"projects/{P}/locations/{LOC}"
    g = gcs(); b = g.create_bucket(f"rag-{TAG}"); b.blob("kb/boiler.txt").upload_from_string(DOC.encode())
    data = rest(av.VertexRagDataServiceClient)
    corpus = data.create_rag_corpus(request={"parent": parent, "rag_corpus": {"display_name": f"kb-{TAG}"}}).result(timeout=60).name
    data.import_rag_files(request={"parent": corpus, "import_rag_files_config": {"gcs_source": {"uris": [f"gs://rag-{TAG}/kb/"]}}}).result(timeout=120)
    cl = genai.Client(vertexai=True, project=P, location=LOC, credentials=Dummy(), http_options=types.HttpOptions(base_url=EP, api_version="v1"))
    tool = types.Tool(retrieval=types.Retrieval(vertex_rag_store=types.VertexRagStore(
        rag_resources=[types.VertexRagStoreRagResource(rag_corpus=corpus)], similarity_top_k=2)))
    cfg = types.GenerateContentConfig(tools=[tool])
    q = "What is the boiler pressure limit?"

    llm.set_backend(None)    # no model: the request must be ACCEPTED (not the old 400) and fail only at the model with the standard 503
    try:
        cl.models.generate_content(model="gemini-2.5-flash", contents=q, config=cfg)
        check("no local model -> standard 503, not 400 'tools.retrieval is not supported'", False, "call succeeded without a model")
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        check("no local model -> standard 503 UNAVAILABLE (retrieval tool accepted)", code == 503, f"{type(e).__name__} {str(e)[:200]}")
    # unknown corpus is a real retrieval error, surfaced before any model call
    bad = types.Tool(retrieval=types.Retrieval(vertex_rag_store=types.VertexRagStore(rag_resources=[types.VertexRagStoreRagResource(rag_corpus=f"{parent}/ragCorpora/999")])))
    try:
        cl.models.generate_content(model="gemini-2.5-flash", contents=q, config=types.GenerateContentConfig(tools=[bad]))
        check("unknown corpus is a retrieval error", False)
    except Exception as e:  # noqa: BLE001
        check("unknown corpus -> 404 NOT_FOUND", getattr(e, "code", None) == 404, f"{getattr(e, 'code', None)} {str(e)[:160]}")

    seen = {}

    def stub(messages, system, max_tokens, temperature, stop):
        seen["system"] = system or next((m["content"] for m in messages if m["role"] == "system"), "")
        return {"text": "The boiler must not exceed 30 psi.", "finish_reason": "stop"}
    llm.set_backend(stub)
    try:
        r = cl.models.generate_content(model="gemini-2.5-flash", contents=q, config=cfg)
    finally:
        llm.set_backend(None)
    check("stub model: retrieved context was injected into the model's system prompt", "30 psi" in seen.get("system", "") and "Retrieved context" in seen.get("system", ""), seen)
    gm = r.candidates[0].grounding_metadata
    check("response has grounding_chunks with the retrieved text", gm is not None and gm.grounding_chunks and "30 psi" in gm.grounding_chunks[0].retrieved_context.text, gm)
    check("response has grounding_supports pointing at a chunk", gm and gm.grounding_supports and gm.grounding_supports[0].grounding_chunk_indices and gm.grounding_supports[0].segment.text.startswith("The boiler"), gm)
    check("retrieval_queries echo the query", gm and list(gm.retrieval_queries or []) == [q], gm)
    check("answer text returned", r.text.strip() == "The boiler must not exceed 30 psi.", r.text)


SUITES = {"1": t_logging, "2": t_trace, "3": t_kms, "4": t_eventfn, "5": t_gcsnotif, "6": t_rag}
if __name__ == "__main__":
    want = sys.argv[1:] or list(SUITES)
    for k in want:
        print(f"== {k} {SUITES[k].__name__}")
        try:
            SUITES[k]()
        except Exception as e:  # noqa: BLE001
            import traceback; traceback.print_exc()
            check(f"{SUITES[k].__name__} ran", False, repr(e))
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    sys.stdout.flush()
    os._exit(1 if FAILED else 0)
