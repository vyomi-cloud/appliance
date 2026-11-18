"""C12: knowledge processing pipeline. Documents -> GCS -> embeddings -> Vertex RAG corpus (import); a new upload re-triggers ingestion through
Eventarc (storage finalized) -> Cloud Run function -> RAG import, and the GCS notification to Pub/Sub; re-uploading a document replaces its old version."""
import os, time
from google.api_core import exceptions as gex
from ..runtime import NAMES, LANE, Blocked, need_grpc
from .. import deploy


def _count(ctx):
    return len(list(ctx.aiplatform("VertexRagDataServiceClient").list_rag_files(request={"parent": ctx.state["rag_corpus"]})))


def run(ctx):
    gcs = ctx.storage()
    bucket = NAMES["bucket"]
    from ..runtime import fixture_dir
    docs_dir = os.path.join(fixture_dir(), "docs")

    def upload():
        try:
            b = gcs.create_bucket(bucket)
        except gex.Conflict:
            b = gcs.bucket(bucket)
        n = 0
        for f in sorted(os.listdir(docs_dir)):
            with open(os.path.join(docs_dir, f), "rb") as fh:
                b.blob("docs/" + f).upload_from_string(fh.read(), content_type="text/markdown")
            n += 1
        return f"{n} documents uploaded to gs://{bucket}/docs/"
    ctx.step("gcs: upload SOP and manual documents (google-cloud-storage)", upload)

    def embed():
        r = ctx.genai().models.embed_content(model="text-embedding-005", contents=["boiler pressure", "elevator contract"])
        v = [e.values for e in r.embeddings]
        assert len(v) == 2 and len(v[0]) > 0
        if not any(abs(x) > 1e-9 for x in v[0]):
            raise Blocked(LANE["model"], "embedding endpoint returned an all-zero vector (no embedding model reachable)")
        return f"embedContent text-embedding-005: dim {len(v[0])}"
    ctx.step("vertex ai: embedContent text-embedding-005 (google-genai)", embed)

    data = ctx.aiplatform("VertexRagDataServiceClient")

    def corpus():
        for c in data.list_rag_corpora(request={"parent": ctx.parent}):
            if c.display_name == NAMES["kb"]:
                ctx.state["rag_corpus"] = c.name
                return c.name
        c = data.create_rag_corpus(request={"parent": ctx.parent, "rag_corpus": {"display_name": NAMES["kb"], "description": "Facilities SOPs and manuals"}}).result(timeout=120)
        ctx.state["rag_corpus"] = c.name
        return c.name
    ctx.step("vertex rag engine: create corpus facilities-kb", corpus)
    if "rag_corpus" not in ctx.state:
        return

    def ingest():
        data.import_rag_files(request={"parent": ctx.state["rag_corpus"], "import_rag_files_config": {"gcs_source": {"uris": [f"gs://{bucket}/docs/"]}}}).result(timeout=180)
        n = _count(ctx)
        assert n >= 4, f"{n} RAG files after import"
        ctx.state["rag_files_before"] = n
        return f"import_rag_files complete: {n} RAG files in the corpus"
    ctx.step("vertex rag engine: import_rag_files from gs://facilities-docs/docs/ + list_rag_files", ingest)
    if "rag_files_before" not in ctx.state:
        return

    def notification():
        need_grpc(ctx, "pubsub")
        from google.cloud import pubsub_v1  # noqa: F401
        pub, sub = ctx.pubsub()
        topic, sname = f"projects/{ctx.project}/topics/{NAMES['docs_topic']}", f"projects/{ctx.project}/subscriptions/{NAMES['docs_sub']}"
        for fn, req in ((pub.create_topic, {"name": topic}), (sub.create_subscription, {"name": sname, "topic": topic})):
            try:
                fn(request=req)
            except gex.AlreadyExists:
                pass
        b = gcs.bucket(bucket)
        b.notification(topic_name=NAMES["docs_topic"], topic_project=ctx.project, event_types=["OBJECT_FINALIZE"], payload_format="JSON_API_V1").create()
        b.blob("docs/notify-probe.md").upload_from_string(b"# Notify probe\nThis object only exists to prove the bucket notification.")
        got = []
        for _ in range(10):
            got = sub.pull(request={"subscription": sname, "max_messages": 5}, timeout=15).received_messages
            if got:
                break
            time.sleep(0.5)
        assert got, "no OBJECT_FINALIZE notification arrived on the Pub/Sub topic"
        a = got[0].message.attributes
        assert a.get("eventType") == "OBJECT_FINALIZE" and a.get("objectId") == "docs/notify-probe.md", dict(a)
        sub.acknowledge(request={"subscription": sname, "ack_ids": [m.ack_id for m in got]})
        b.blob("docs/notify-probe.md").delete()
        return "bucket notification OBJECT_FINALIZE reached the topic with the object id"
    ctx.step("gcs: bucket notification (OBJECT_FINALIZE -> Pub/Sub) on upload", notification, lane=LANE["core"])

    def event_driven():
        from google.cloud import eventarc_v1 as ea
        ctx.state["ingest_uri"] = deploy.deploy_function(ctx, "facilities-ingest-docs", "ingest_docs", cloudevent=True)
        ec = ctx.rest(ea.EventarcClient)
        trig = ea.Trigger(name=f"{ctx.parent}/triggers/facilities-docs-finalized",
                          event_filters=[ea.EventFilter(attribute="type", value="google.cloud.storage.object.v1.finalized"), ea.EventFilter(attribute="bucket", value=bucket)],
                          destination=ea.Destination(cloud_run=ea.CloudRun(service="facilities-ingest-docs", region=ctx.loc)))
        try:
            ec.create_trigger(request={"parent": ctx.parent, "trigger": trig, "trigger_id": "facilities-docs-finalized"}).result(timeout=60)
        except gex.AlreadyExists:
            pass
        before = _count(ctx)
        gcs.bucket(bucket).blob("docs/safety-bulletin-2026-11.md").upload_from_string(
            b"# Bulletin 2026-11\nChilled water loop flush is scheduled for Saturday. Notify tenants on floors 3 to 5.")
        for _ in range(40):
            after = _count(ctx)
            if after > before:
                return f"new upload triggered the function, RAG files {before} -> {after}"
            time.sleep(0.5)
        raise Blocked(LANE["sandbox"], "the finalize event did not result in a RAG import (Eventarc -> function -> SDK call inside the function sandbox)")
    ctx.step("eventarc: object finalized -> Cloud Run function -> RAG import (event-driven re-index)", event_driven, lane=LANE["sandbox"])

    def reingest():
        retr = ctx.aiplatform("VertexRagServiceClient")
        gcs.bucket(bucket).blob("docs/boiler-sop.md").upload_from_string(b"# Boiler SOP rev 2\nBoiler pressure limit is now 25 psi after the 2026 revision.")
        data.import_rag_files(request={"parent": ctx.state["rag_corpus"], "import_rag_files_config": {"gcs_source": {"uris": [f"gs://{bucket}/docs/boiler-sop.md"]}}}).result(timeout=120)
        r = retr.retrieve_contexts(request={"parent": ctx.parent, "query": {"text": "boiler pressure limit psi", "rag_retrieval_config": {"top_k": 4}},
                                            "vertex_rag_store": {"rag_resources": [{"rag_corpus": ctx.state["rag_corpus"]}]}})
        txt = " ".join(c.text for c in r.contexts.contexts if "boiler-sop" in c.source_uri)
        assert "25 psi" in txt and "30 psi" not in txt, f"stale chunk still served after re-ingest: {txt[:200]}"
        # put the original back so the rest of the run (and the cited answer) uses the fixture
        with open(os.path.join(docs_dir, "boiler-sop.md"), "rb") as fh:
            gcs.bucket(bucket).blob("docs/boiler-sop.md").upload_from_string(fh.read())
        data.import_rag_files(request={"parent": ctx.state["rag_corpus"], "import_rag_files_config": {"gcs_source": {"uris": [f"gs://{bucket}/docs/boiler-sop.md"]}}}).result(timeout=120)
        return "re-upload + re-import replaced the old version (only 25 psi served), fixture restored"
    ctx.step("vertex rag engine: re-upload a revised SOP and re-import: only the new version is served", reingest)
