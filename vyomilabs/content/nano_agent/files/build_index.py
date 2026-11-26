"""Build the knowledge index: split the handbook into passages, embed each one, store the index in S3 next to the documents."""
import seed
from data import DOCS
from rag import build_index, chunk

seed.seed()
for name, text in list(DOCS.items())[:2]:
    print(name, "->", [c["text"][:48] + "..." for c in chunk(name, text)])
chunks = build_index(DOCS)
print("indexed", len(chunks), "passages from", len(DOCS), "documents; each has a vector of", len(chunks[0]["vec"]), "numbers")
assert len(chunks) >= len(DOCS) and len(chunks[0]["vec"]) > 100
print("index built")
