import gcp
from google.cloud import aiplatform_v1 as av

KB_NAME = "facilities-kb"


def data_client():
    return gcp.rest(av.VertexRagDataServiceClient)


def search_client():
    return gcp.rest(av.VertexRagServiceClient)


def corpus_name():
    for c in data_client().list_rag_corpora(request={"parent": gcp.PARENT}):
        if c.display_name == KB_NAME:
            return c.name
    return None


def import_uris(corpus, uris):
    data_client().import_rag_files(request={"parent": corpus, "import_rag_files_config": {"gcs_source": {"uris": uris}}}).result(timeout=180)


def files(corpus):
    return list(data_client().list_rag_files(request={"parent": corpus}))
