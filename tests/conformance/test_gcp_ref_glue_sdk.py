"""GCP reference-app glue fixes (round 2, lane 7), proved with the unmodified Google client libraries on the REAL Pub/Sub + Firestore emulators.

  1. GCS bucket notifications reach an emulator gRPC subscriber (OBJECT_FINALIZE / OBJECT_DELETE) with VYOMI_GCP_REAL_BACKENDS=1,
     and an Eventarc-triggered function fires exactly once for the same upload.
  2. Pub/Sub admin calls made by a gRPC client against the emulator appear in Cloud Audit Logs (cloudaudit.googleapis.com%2Factivity),
     once each (a REST-made topic is not audited twice).
  3. The gRPC front starts by itself in real-backend mode (no VYOMI_GCP_GRPC_PORT) and the DEFAULT monitoring_v3.MetricServiceClient /
     logging.Client work against the endpoint it advertises (env + discovery document).
  4. API Gateway forwards the real ESPv2 header X-Apigateway-Api-Userinfo (and the old X-Endpoint-API-UserInfo) to a deployed Cloud Run
     function reached with an Identity Platform ID token; a forged header from the caller is replaced.
Function stdout reaching Cloud Logging (5) is covered in test_gcp_ref_corefix_sdk.py::t_eventfn.
Needs docker + the local emulator image (never pulled); SKIPs cleanly otherwise. Run: PYTHONPATH=. python3 tests/conformance/test_gcp_ref_glue_sdk.py
"""
import base64
import io
import json
import os
import sys
import threading
import time
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from test_gcp_real_backends import start_emulators, start_sim, NAMES, sh, ok, FAILS, PROJECT as P   # noqa: E402

TAG = uuid.uuid4().hex[:6]
LOC = "us-central1"


def main():
    try:
        import google.cloud.pubsub_v1, google.cloud.storage, google.cloud.logging, google.cloud.monitoring_v3, requests  # noqa: F401
        from google.cloud import functions_v2, apigateway_v1  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] needs the Google client libraries ({e})")
        return 0
    pp, fp = start_emulators()
    try:
        run(pp, fp)
    finally:
        for n in NAMES:
            sh("docker", "rm", "-f", n)
    print("\n" + ("ALL PASS" if not FAILS else f"FAILED: {FAILS}"))
    return 1 if FAILS else 0


def run(pp, fp):
    os.environ.update(VYOMI_GCP_REAL_BACKENDS="1", PUBSUB_EMULATOR_HOST=f"127.0.0.1:{pp}", FIRESTORE_EMULATOR_HOST=f"127.0.0.1:{fp}", GOOGLE_CLOUD_PROJECT=P)
    sim, router = start_sim()
    base = f"http://{sim}"
    os.environ["VYOMI_SELF_ENDPOINT"] = base
    import requests
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import functions_v2 as f2, pubsub_v1, storage
    import google.cloud.logging as gl
    from core import gcp_grpc_front

    anon = AnonymousCredentials()
    opts = ClientOptions(api_endpoint=base)
    gcs = storage.Client(project=P, credentials=anon, client_options=opts)
    pub, sub = pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()       # default gRPC -> the emulator (PUBSUB_EMULATOR_HOST)

    def rest_logs():
        c = gl.Client(project=P, credentials=anon, _use_grpc=False, client_options=opts)
        c._connection.API_BASE_URL = base
        return c

    def deploy(fid, src, sig=None):
        fc = f2.FunctionServiceClient(credentials=anon, transport="rest", client_options=opts)
        parent = f"projects/{P}/locations/{LOC}"
        up = fc.generate_upload_url(request={"parent": parent})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("main.py", src)
            z.writestr("requirements.txt", "functions-framework\n")
        requests.put(up.upload_url, data=buf.getvalue(), headers={"content-type": "application/zip"}, timeout=60).raise_for_status()
        bc = dict(runtime="python312", entry_point="handler", source=f2.Source(storage_source=up.storage_source))
        if sig:
            bc["environment_variables"] = {"GOOGLE_FUNCTION_SIGNATURE_TYPE": sig}
        fc.create_function(request={"parent": parent, "function_id": fid, "function": f2.Function(
            name=f"{parent}/functions/{fid}", build_config=f2.BuildConfig(**bc), service_config=f2.ServiceConfig(available_memory="256M", timeout_seconds=60))}).result(timeout=120)

    # ── 1. GCS notifications -> emulator gRPC subscriber; Eventarc function fires once ───────────────────────────
    topic, sname = f"projects/{P}/topics/gcs-{TAG}", f"projects/{P}/subscriptions/gcs-{TAG}"
    pub.create_topic(request={"name": topic})
    sub.create_subscription(request={"name": sname, "topic": topic})
    b = gcs.create_bucket(f"glue-{TAG}")
    b.notification(topic_name=f"gcs-{TAG}", topic_project=P, event_types=["OBJECT_FINALIZE", "OBJECT_DELETE"], payload_format="JSON_API_V1").create()
    got: list = []
    fut = sub.subscribe(sname, callback=lambda m: (got.append(m), m.ack()))   # the unmodified gRPC streaming-pull subscriber
    deploy(f"onfin{TAG}", "import functions_framework\n\n@functions_framework.cloud_event\ndef handler(event):\n    print('EVTFIRED', event.data.get('name'))\n    return 'ok'\n", "cloudevent")
    r = requests.post(f"{base}/v1/projects/{P}/locations/{LOC}/triggers", params={"triggerId": f"fin{TAG}"}, headers={"Authorization": "Bearer x"}, json={
        "eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": b.name}],
        "destination": {"cloudRun": {"service": f"onfin{TAG}", "region": LOC}}})
    ok("Eventarc trigger created", r.status_code in (200, 201), r.text[:200])
    b.blob("docs/a.md").upload_from_string(b"hello")
    for _ in range(40):
        if any(m.attributes.get("eventType") == "OBJECT_FINALIZE" for m in got):
            break
        time.sleep(0.25)
    fin = [m for m in got if m.attributes.get("eventType") == "OBJECT_FINALIZE"]
    ok("emulator gRPC subscriber receives OBJECT_FINALIZE from the bucket notification", len(fin) == 1 and fin[0].attributes.get("objectId") == "docs/a.md" and fin[0].attributes.get("bucketId") == b.name,
       [dict(m.attributes) for m in got][:2])
    b.blob("docs/a.md").delete()
    for _ in range(40):
        if any(m.attributes.get("eventType") == "OBJECT_DELETE" for m in got):
            break
        time.sleep(0.25)
    ok("... and OBJECT_DELETE", any(m.attributes.get("eventType") == "OBJECT_DELETE" and m.attributes.get("objectId") == "docs/a.md" for m in got))
    fut.cancel()
    time.sleep(3)
    fired = [e for e in rest_logs().list_entries(filter_='logName="projects/%s/logs/run.googleapis.com%%2Fstdout"' % P) if "EVTFIRED docs/a.md" in str(e.payload)]
    ok("Eventarc-triggered function fired exactly once for the upload (stdout in Cloud Logging)", len(fired) == 1, len(fired))

    # ── 2. admin calls made over gRPC are audited ───────────────────────────────────────────────────────────────
    atopic = f"projects/{P}/topics/audit-{TAG}"
    pub.create_topic(request={"name": atopic})
    sub.create_subscription(request={"name": f"projects/{P}/subscriptions/audit-{TAG}", "topic": atopic})
    requests.put(f"{base}/v1/projects/{P}/topics/restaudit-{TAG}", json={})
    pub.delete_topic(request={"topic": f"projects/{P}/topics/gcs-{TAG}"})
    want = {"google.pubsub.v1.Publisher.CreateTopic": f"audit-{TAG}", "google.pubsub.v1.Subscriber.CreateSubscription": f"audit-{TAG}",
            "google.pubsub.v1.Publisher.DeleteTopic": f"gcs-{TAG}"}
    seen: dict = {}
    for _ in range(40):
        es = list(rest_logs().list_entries(filter_='logName="projects/%s/logs/cloudaudit.googleapis.com%%2Factivity"' % P))
        seen = {}
        for e in es:
            pl = e.payload if isinstance(e.payload, dict) else {}
            seen.setdefault((pl.get("methodName"), str(pl.get("resourceName", "")).rsplit("/", 1)[-1]), 0)
            seen[(pl.get("methodName"), str(pl.get("resourceName", "")).rsplit("/", 1)[-1])] += 1
        if all((m, n) in seen for m, n in want.items()):
            break
        time.sleep(0.5)
    ok("gRPC CreateTopic / CreateSubscription / DeleteTopic appear in Cloud Audit Logs (admin activity)", all((m, n) in seen for m, n in want.items()), seen)
    ok("each is audited once", all(seen.get((m, n)) == 1 for m, n in want.items()), seen)
    ok("a topic created through the simulator REST door is audited exactly once (no double entry)",
       seen.get(("google.pubsub.v1.Publisher.CreateTopic", f"restaudit-{TAG}")) == 1, seen)

    # ── 3. gRPC front: auto-start, advertised endpoint, DEFAULT clients ─────────────────────────────────────────
    os.environ.pop("VYOMI_GCP_GRPC_PORT", None)
    gport = gcp_grpc_front.maybe_start(upstream=base, port=0)
    d = gcp_grpc_front.discovery()
    ok("gRPC front starts by itself with VYOMI_GCP_REAL_BACKENDS=1 and advertises endpoint + CA",
       gport > 0 and d.get("enabled") and d["endpoint"] == os.environ.get("VYOMI_GCP_GRPC_ENDPOINT") and "BEGIN CERTIFICATE" in d.get("ca_pem", ""), d.get("endpoint"))
    os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = os.environ["VYOMI_GCP_GRPC_CA"]
    from google.cloud import monitoring_v3
    ep = d["endpoint"]
    mc = monitoring_v3.MetricServiceClient(credentials=anon, client_options={"api_endpoint": ep})
    mt = f"custom.googleapis.com/glue/{TAG}"
    mc.create_metric_descriptor(name=f"projects/{P}", metric_descriptor={"type": mt, "metric_kind": "GAUGE", "value_type": "INT64"})
    now = int(time.time())
    mc.create_time_series(name=f"projects/{P}", time_series=[monitoring_v3.TimeSeries({"metric": {"type": mt}, "resource": {"type": "global", "labels": {"project_id": P}},
                                                                                    "points": [{"interval": {"end_time": {"seconds": now}}, "value": {"int64_value": 7}}]})])
    ts = list(mc.list_time_series(request={"name": f"projects/{P}", "filter": f'metric.type="{mt}"', "interval": {"end_time": {"seconds": now + 60}, "start_time": {"seconds": now - 600}}}))
    ok("default monitoring_v3.MetricServiceClient: create descriptor + time series + list over the advertised gRPC endpoint", len(ts) == 1 and ts[0].points[0].value.int64_value == 7)
    lc = gl.Client(project=P, credentials=anon, client_options={"api_endpoint": ep})
    lc.logger(f"glue-{TAG}").log_struct({"k": "v", "tag": TAG})
    ents = []
    for _ in range(10):
        ents = list(lc.list_entries(filter_=f'logName="projects/{P}/logs/glue-{TAG}"'))
        if ents:
            break
        time.sleep(0.5)
    ok("default logging.Client (gRPC): log_struct + list_entries", [e.payload.get("tag") for e in ents if isinstance(e.payload, dict) and e.payload.get("tag")] == [TAG], len(ents))

    # ── 4. API Gateway -> deployed Cloud Run function: real ESPv2 identity header ───────────────────────────────
    deploy(f"echo{TAG}", "import json, functions_framework\n\n@functions_framework.http\ndef handler(request):\n    h = request.headers\n"
           "    return json.dumps({'new': h.get('X-Apigateway-Api-Userinfo', ''), 'old': h.get('X-Endpoint-API-UserInfo', '')})\n")
    r = requests.post(f"{base}/v1/accounts:signUp?key=fake", json={"email": f"caller{TAG}@example.com", "password": "pw-12345", "returnSecureToken": True})
    tok = r.json()["idToken"]
    spec = {"swagger": "2.0", "info": {"title": "glue", "version": "1.0"}, "schemes": ["https"], "produces": ["application/json"],
            "paths": {"/whoami": {"get": {"operationId": "whoami", "security": [{"firebase": []}], "responses": {"200": {"description": "ok"}},
                                          "x-google-backend": {"address": f"https://{LOC}-{P}.cloudfunctions.net/echo{TAG}", "path_translation": "APPEND_PATH_TO_ADDRESS"}}}},
            "securityDefinitions": {"firebase": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": "https://securetoken.google.com/" + P,
                                                 "x-google-jwks_uri": "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com", "x-google-audiences": P}}}
    from google.cloud import apigateway_v1
    gc = apigateway_v1.ApiGatewayServiceClient(transport="rest", credentials=anon, client_options={"api_endpoint": base})
    par = f"projects/{P}/locations/global"
    gc.create_api(request={"parent": par, "api_id": f"glue{TAG}", "api": {"display_name": "glue"}}).result()
    gc.create_api_config(request={"parent": f"{par}/apis/glue{TAG}", "api_config_id": "c1", "api_config": {
        "openapi_documents": [{"document": {"path": "openapi.json", "contents": json.dumps(spec).encode()}}]}}).result()
    gw = gc.create_gateway(request={"parent": f"projects/{P}/locations/{LOC}", "gateway_id": f"glue{TAG}", "gateway": {"api_config": f"{par}/apis/glue{TAG}/configs/c1"}}).result()
    resp = requests.get(base + "/whoami", headers={"Host": gw.default_hostname, "Authorization": "Bearer " + tok, "X-Apigateway-Api-Userinfo": "forged"})
    ok("gateway -> Cloud Run function with an Identity Platform token returns 200", resp.status_code == 200, (resp.status_code, resp.text[:200]))
    body = resp.json() if resp.status_code == 200 else {}
    pad = lambda s: s + "=" * (-len(s) % 4)
    claims = json.loads(base64.urlsafe_b64decode(pad(body.get("new", "")))) if body.get("new") and body["new"] != "forged" else {}
    ok("function sees X-Apigateway-Api-Userinfo = base64url JSON of the verified claims (caller's forged value replaced)", claims.get("email") == f"caller{TAG}@example.com", body)
    ok("the older X-Endpoint-API-UserInfo is still forwarded", body.get("old") == body.get("new") and bool(body.get("old")), body)


if __name__ == "__main__":
    sys.exit(main())
