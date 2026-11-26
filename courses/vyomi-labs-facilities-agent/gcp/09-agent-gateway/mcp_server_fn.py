import json
import os

# RAG_TOP_K is your RAG design (chapter 14): register_tools.py sets it when it deploys this function.


def _kb_search(args):
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import aiplatform_v1 as av
    endpoint = os.environ.get("VERTEX_API_ENDPOINT")
    if endpoint:
        client = av.VertexRagServiceClient(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=endpoint))
    else:
        client = av.VertexRagServiceClient()
    parent = f"projects/{os.environ['GOOGLE_CLOUD_PROJECT']}/locations/{os.environ.get('GOOGLE_CLOUD_REGION', 'us-central1')}"
    r = client.retrieve_contexts(request={"parent": parent, "query": {"text": args.get("query", ""), "rag_retrieval_config": {"top_k": int(args.get("top_k", os.environ.get("RAG_TOP_K", 3)))}},
                                          "vertex_rag_store": {"rag_resources": [{"rag_corpus": os.environ["RAG_CORPUS"]}]}})
    return {"results": [{"text": c.text, "score": getattr(c, "score", None), "source": c.source_uri} for c in r.contexts.contexts]}


def _asset_status(args):
    from google.cloud import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter
    db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
    snap = db.collection(os.environ.get("ASSETS_COLLECTION", "assets")).document(args["asset_id"]).get()
    if not snap.exists:
        return {"found": False}
    orders = db.collection(os.environ.get("WORK_ORDERS_COLLECTION", "work-orders")).where(filter=FieldFilter("asset_id", "==", args["asset_id"])).stream()
    return {"found": True, "asset": snap.to_dict(), "work_orders": [d.to_dict() for d in orders]}


TOOLS = [
    {"name": "kb_search", "description": "Search the facilities knowledge base (read-only).",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "asset_status", "description": "Look up an asset and its work orders (read-only).",
     "inputSchema": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}},
]
IMPL = {"kb_search": _kb_search, "asset_status": _asset_status}


def _reply(rid, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": rid}
    out.update({"error": error} if error else {"result": result})
    return out


def handler(request):
    msg = request.get_json(silent=True) or {}
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return _reply(rid, {"protocolVersion": params.get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}},
                            "serverInfo": {"name": "facilities-tools", "version": "1.0.0"}})
    if method and method.startswith("notifications/"):
        return {}
    if method == "tools/list":
        return _reply(rid, {"tools": TOOLS})
    if method == "tools/call":
        fn = IMPL.get(params.get("name"))
        if not fn:
            return _reply(rid, error={"code": -32602, "message": f"unknown tool {params.get('name')}"})
        try:
            return _reply(rid, {"content": [{"type": "text", "text": json.dumps(fn(params.get("arguments") or {}))}], "isError": False})
        except Exception as e:
            return _reply(rid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
    return _reply(rid, error={"code": -32601, "message": f"method not found: {method}"})
