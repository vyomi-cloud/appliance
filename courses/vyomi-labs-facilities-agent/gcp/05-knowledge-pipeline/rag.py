import gcp
import rag_design
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


def import_config(uris):
    cfg = {"gcs_source": {"uris": uris}}
    if rag_design.customised("chunking"):          # your design: chunk size and overlap (the overlap is a percentage of the size in the design)
        c = rag_design.chunk_cfg()
        cfg["rag_file_transformation_config"] = {"rag_file_chunking_config": {"fixed_length_chunking": {
            "chunk_size": c["maxTokens"], "chunk_overlap": round(c["maxTokens"] * c["overlapPct"] / 100)}}}
    return cfg


def import_uris(corpus, uris):
    data_client().import_rag_files(request={"parent": corpus, "import_rag_files_config": import_config(uris)}).result(timeout=180)


def files(corpus):
    return list(data_client().list_rag_files(request={"parent": corpus}))
