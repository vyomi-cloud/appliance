import os

import functions_framework


@functions_framework.cloud_event
def handler(event):
    data = getattr(event, "data", None) or event
    data = data if isinstance(data, dict) else {}
    name, bucket = data.get("name", ""), data.get("bucket", "facilities-docs")
    if not name.startswith("docs/"):
        return "ignored"
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import aiplatform_v1 as av
    endpoint = os.environ.get("VERTEX_API_ENDPOINT")
    if endpoint:       # the simulator; on real Google Cloud leave this variable unset and the client uses Application Default Credentials
        client = av.VertexRagDataServiceClient(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=endpoint))
    else:
        client = av.VertexRagDataServiceClient()
    cfg = {"gcs_source": {"uris": [f"gs://{bucket}/{name}"]}}
    import rag_design
    if rag_design.customised("chunking"):          # your design: chunk size and overlap
        c = rag_design.chunk_cfg()
        cfg["rag_file_transformation_config"] = {"rag_file_chunking_config": {"fixed_length_chunking": {
            "chunk_size": c["maxTokens"], "chunk_overlap": round(c["maxTokens"] * c["overlapPct"] / 100)}}}
    client.import_rag_files(request={"parent": os.environ["RAG_CORPUS"], "import_rag_files_config": cfg}).result(timeout=120)
    return "imported " + name
