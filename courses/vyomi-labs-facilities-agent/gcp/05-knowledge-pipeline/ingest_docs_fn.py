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
    if os.environ.get("RAG_CHUNK_SIZE"):           # your design (chapter 14): set when the function is deployed, only if the design changes the chunking
        cfg["rag_file_transformation_config"] = {"rag_file_chunking_config": {"fixed_length_chunking": {
            "chunk_size": int(os.environ["RAG_CHUNK_SIZE"]), "chunk_overlap": int(os.environ["RAG_CHUNK_OVERLAP"])}}}
    client.import_rag_files(request={"parent": os.environ["RAG_CORPUS"], "import_rag_files_config": cfg}).result(timeout=120)
    return "imported " + name
