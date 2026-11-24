from google.genai import types

import gcp
import rag

corpus = rag.corpus_name()
tool = types.Tool(retrieval=types.Retrieval(vertex_rag_store=types.VertexRagStore(
    rag_resources=[types.VertexRagStoreRagResource(rag_corpus=corpus)], similarity_top_k=2)))
from models import CHAT_MODEL
client = gcp.genai_client()          # keep a reference: a garbage-collected genai client closes its HTTP session
r = client.models.generate_content(model=CHAT_MODEL, contents="What should I do when boiler pressure exceeds 30 psi?",
                                   config=types.GenerateContentConfig(tools=[tool]))
meta = r.candidates[0].grounding_metadata
chunks = meta.grounding_chunks or []
print("grounding chunks:", len(chunks))
assert chunks and r.text
print("generateContent grounded on the RAG corpus")
