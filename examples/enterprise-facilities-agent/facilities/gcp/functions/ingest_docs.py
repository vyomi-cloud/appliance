"""Knowledge pipeline trigger (Eventarc, storage object finalized): an object landing under docs/ is imported into the RAG corpus."""
import os


def handler(event):
    data = getattr(event, "data", None) or event
    data = data if isinstance(data, dict) else {}
    name, bucket = data.get("name", ""), data.get("bucket") or os.environ["DOCS_BUCKET"]
    if not name.startswith("docs/"):
        return "ignored"
    from google.cloud import aiplatform_v1 as av
    ep = os.environ.get("VERTEX_API_ENDPOINT")
    if ep:
        from google.api_core.client_options import ClientOptions
        from google.auth.credentials import AnonymousCredentials
        client = av.VertexRagDataServiceClient(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=ep))
    else:
        client = av.VertexRagDataServiceClient()
    client.import_rag_files(request={"parent": os.environ["RAG_CORPUS"], "import_rag_files_config": {"gcs_source": {"uris": [f"gs://{bucket}/{name}"]}}}).result(timeout=120)
    return "imported " + name
