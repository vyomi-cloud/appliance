from kb_index import index_client
from azdata import INDEX

ix = index_client().get_index(INDEX)
print("fields:", [(f.name, "vector" if f.name == "content_vector" else "text/key") for f in ix.fields])
print("vector dimensions:", next(f.vector_search_dimensions for f in ix.fields if f.name == "content_vector"))
print("semantic configurations:", [c.name for c in ix.semantic_search.configurations])
