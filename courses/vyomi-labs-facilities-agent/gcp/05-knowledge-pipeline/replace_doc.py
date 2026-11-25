import gcp
import rag
from docs import DOCS

corpus = rag.corpus_name()
blob = gcp.storage_client().bucket("facilities-docs").blob("docs/boiler-sop.md")


def boiler_text():
    r = rag.search_client().retrieve_contexts(request={"parent": gcp.PARENT, "query": {"text": "boiler pressure limit psi", "rag_retrieval_config": {"top_k": 4}},
                                                       "vertex_rag_store": {"rag_resources": [{"rag_corpus": corpus}]}})
    return " ".join(c.text for c in r.contexts.contexts if "boiler-sop" in c.source_uri)


blob.upload_from_string(b"# Boiler SOP rev 2\nBoiler pressure limit is now 25 psi after the 2026 revision.")
rag.import_uris(corpus, ["gs://facilities-docs/docs/boiler-sop.md"])
text = boiler_text()
assert "25 psi" in text and "30 psi" not in text, text
print("after revision only 25 psi is served")

blob.upload_from_string(DOCS["boiler-sop.md"].encode())
rag.import_uris(corpus, ["gs://facilities-docs/docs/boiler-sop.md"])
print("original restored serves 30 psi:", "30 psi" in boiler_text())
