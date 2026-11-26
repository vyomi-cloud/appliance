import base64
import json
import os

# RAG_TOP_K is your RAG design (chapter 14): deploy_kb_search.py sets it when it deploys this function.


def handler(request):
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import aiplatform_v1 as av
    body = request.get_json(silent=True) or {}
    endpoint = os.environ.get("VERTEX_API_ENDPOINT")
    if endpoint:       # the simulator; on real Google Cloud leave this unset and Application Default Credentials are used
        client = av.VertexRagServiceClient(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=endpoint))
    else:
        client = av.VertexRagServiceClient()
    parent = f"projects/{os.environ['GOOGLE_CLOUD_PROJECT']}/locations/{os.environ.get('GOOGLE_CLOUD_REGION', 'us-central1')}"
    r = client.retrieve_contexts(request={"parent": parent, "query": {"text": body.get("query", ""), "rag_retrieval_config": {"top_k": int(body.get("top_k", os.environ.get("RAG_TOP_K", 3)))}},
                                          "vertex_rag_store": {"rag_resources": [{"rag_corpus": os.environ["RAG_CORPUS"]}]}})
    caller = "anonymous"
    info = request.headers.get("X-Apigateway-Api-Userinfo")
    if info:
        try:
            caller = json.loads(base64.urlsafe_b64decode(info + "=" * (-len(info) % 4))).get("email", "anonymous")
        except Exception:
            pass
    return {"results": [{"text": c.text, "score": getattr(c, "score", None), "source": c.source_uri} for c in r.contexts.contexts], "caller": caller}
