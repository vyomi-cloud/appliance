"""Shared tool logic for the Cloud Run functions (kb-search over Vertex RAG Engine, asset-status over Firestore).
Plain Google client code that runs unchanged on real GCP: with no *_ENDPOINT / *_EMULATOR_HOST variable it uses Application Default Credentials and the
real endpoints. On the simulator the deployer sets VERTEX_API_ENDPOINT (REST) and FIRESTORE_EMULATOR_HOST (the standard emulator variable)."""
import os


def _rag_client():
    from google.cloud import aiplatform_v1 as av
    ep = os.environ.get("VERTEX_API_ENDPOINT")
    if ep:
        from google.api_core.client_options import ClientOptions
        from google.auth.credentials import AnonymousCredentials
        return av.VertexRagServiceClient(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=ep))
    return av.VertexRagServiceClient()


def _db():
    from google.cloud import firestore
    return firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])


def kb_search(args):
    parent = f"projects/{os.environ['GOOGLE_CLOUD_PROJECT']}/locations/{os.environ.get('GOOGLE_CLOUD_REGION', 'us-central1')}"
    r = _rag_client().retrieve_contexts(request={
        "parent": parent, "query": {"text": args.get("query", ""), "rag_retrieval_config": {"top_k": int(args.get("top_k", 3))}},
        "vertex_rag_store": {"rag_resources": [{"rag_corpus": os.environ["RAG_CORPUS"]}]}})
    return {"results": [{"text": c.text, "score": getattr(c, "score", None), "source": c.source_uri} for c in r.contexts.contexts]}


def asset_status(args):
    db = _db()
    snap = db.collection(os.environ.get("ASSETS_COLLECTION", "assets")).document(args["asset_id"]).get()
    if not snap.exists:
        return {"found": False}
    from google.cloud.firestore_v1.base_query import FieldFilter
    wos = [d.to_dict() for d in db.collection(os.environ.get("WORK_ORDERS_COLLECTION", "work-orders")).where(filter=FieldFilter("asset_id", "==", args["asset_id"])).stream()]
    return {"found": True, "asset": snap.to_dict(), "work_orders": wos}
