"""C12 Pipeline: GCS upload -> notification (Pub/Sub) and Eventarc trigger -> function; then RAG file import and retrieval so a re-uploaded SOP becomes searchable."""
from _common import *
import json, time

s = Step()
P = PROJECT
BUCKET = f"sop-{TAG}"
PARENT = f"projects/{P}/locations/{LOC}"


def setup():
    from google.cloud import aiplatform_v1 as av
    s.gcs = storage()
    s.gcs.create_bucket(BUCKET)
    s.gcs.bucket(BUCKET).blob("sop/boiler.txt").upload_from_string(DOC.encode())
    pub, sub = pubsub()
    s.topic, s.subn = f"projects/{P}/topics/gcs-{TAG}", f"projects/{P}/subscriptions/gcs-{TAG}"
    pub.create_topic(request={"name": s.topic}); sub.create_subscription(request={"name": s.subn, "topic": s.topic})
    s.sub = sub
    data = rest_client(av.VertexRagDataServiceClient)
    s.rag = data
    s.corpus = data.create_rag_corpus(request={"parent": PARENT, "rag_corpus": {"display_name": f"sops-{TAG}"}}).result(timeout=60).name
    return "bucket, topic+subscription, RAG corpus"


def gcs_notification():
    b = s.gcs.bucket(BUCKET)
    n = b.notification(topic_name=f"gcs-{TAG}", topic_project=P, event_types=["OBJECT_FINALIZE"], payload_format="JSON_API_V1")
    n.create()
    b.blob("sop/notify.txt").upload_from_string(b"notify me")
    for _ in range(10):
        got = s.sub.pull(request={"subscription": s.subn, "max_messages": 5, "return_immediately": True}, timeout=20).received_messages
        if got:
            break
        time.sleep(0.5)
    assert got, "no OBJECT_FINALIZE notification arrived on the Pub/Sub topic"
    m = got[0].message
    assert m.attributes.get("eventType") == "OBJECT_FINALIZE" and m.attributes.get("objectId") == "sop/notify.txt", dict(m.attributes)
    s.sub.acknowledge(request={"subscription": s.subn, "ack_ids": [got[0].ack_id]})
    return "OBJECT_FINALIZE for sop/notify.txt on the topic"


def eventarc():
    deploy_function(f"onfinal-{TAG}", "def handler(event):\n    print('FINALIZED', event.data.get('name') if hasattr(event, 'data') else event)\n    return 'ok'\n")
    T = f"/v1/{PARENT}/triggers"
    call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": BUCKET}],
                     "destination": {"cloudRun": {"service": f"onfinal-{TAG}", "region": LOC}}}, params={"triggerId": f"fin-{TAG}"})
    s.gcs.bucket(BUCKET).blob("sop/second.txt").upload_from_string(b"Second SOP: chiller service quarterly.")
    d = {}
    for _ in range(20):
        d = call("GET", f"{T}/fin-{TAG}/deliveries")
        if d.get("delivered", 0) >= 1:
            break
        time.sleep(0.5)
    assert d.get("delivered", 0) >= 1, f"Eventarc trigger never delivered the finalize event to the function: {d}"
    return f"delivered={d['delivered']}"


def rag_import():
    s.rag.import_rag_files(request={"parent": s.corpus, "import_rag_files_config": {"gcs_source": {"uris": [f"gs://{BUCKET}/sop/"]}}}).result(timeout=120)
    from google.cloud import aiplatform_v1 as av
    svc = rest_client(av.VertexRagServiceClient)
    r = svc.retrieve_contexts(request={"parent": PARENT, "query": {"text": "boiler 30 psi", "rag_retrieval_config": {"top_k": 1}}, "vertex_rag_store": {"rag_resources": [{"rag_corpus": s.corpus}]}})
    ctx = list(r.contexts.contexts)
    assert ctx and "30 psi" in ctx[0].text, r
    return "uploaded SOP is now retrievable"


def reingest():
    s.gcs.bucket(BUCKET).blob("sop/boiler.txt").upload_from_string(b"Boiler pressure limit is now 25 psi after the 2026 revision.")
    s.rag.import_rag_files(request={"parent": s.corpus, "import_rag_files_config": {"gcs_source": {"uris": [f"gs://{BUCKET}/sop/boiler.txt"]}}}).result(timeout=120)
    from google.cloud import aiplatform_v1 as av
    svc = rest_client(av.VertexRagServiceClient)
    r = svc.retrieve_contexts(request={"parent": PARENT, "query": {"text": "boiler pressure limit psi", "rag_retrieval_config": {"top_k": 3}}, "vertex_rag_store": {"rag_resources": [{"rag_corpus": s.corpus}]}})
    txt = " ".join(c.text for c in r.contexts.contexts)
    assert "25 psi" in txt and "30 psi" not in txt, f"stale chunk still served after re-ingest: {txt[:200]}"
    return "re-import replaced the old version"


s("setup: bucket + Pub/Sub topic/subscription + RAG corpus", setup)
if hasattr(s, "corpus"):
    s("GCS bucket notification (OBJECT_FINALIZE -> Pub/Sub) on upload", gcs_notification)
    s("Eventarc trigger (storage finalized) delivers to a Cloud Function", eventarc)
    s("RAG import_rag_files from the bucket, then retrieve the SOP", rag_import)
    s("re-upload the SOP and re-import: only the new version is served", reingest)
s.finish()
