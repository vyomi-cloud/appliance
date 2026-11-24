import gcp
import rag

corpus = rag.corpus_name()
if not corpus:
    corpus = rag.data_client().create_rag_corpus(request={"parent": gcp.PARENT, "rag_corpus": {
        "display_name": rag.KB_NAME, "description": "Facilities SOPs and manuals"}}).result(timeout=120).name
print("corpus:", corpus)
rag.import_uris(corpus, ["gs://facilities-docs/docs/"])
indexed = rag.files(corpus)
print("indexed files:", len(indexed))
assert len(indexed) >= 4
