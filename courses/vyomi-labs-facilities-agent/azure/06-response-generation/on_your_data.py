from azlab import aoai, CHAT
from azdata import search_endpoint, search_key, INDEX

r = aoai("2025-03-01-preview").chat.completions.create(model=CHAT, messages=[{"role": "user", "content": "What is the boiler pressure rule?"}], extra_body={
    "data_sources": [{"type": "azure_search", "parameters": {"endpoint": search_endpoint(), "index_name": INDEX,
                                                            "authentication": {"type": "api_key", "key": search_key()}}}]})
context = getattr(r.choices[0].message, "context", None) or {}
print("On Your Data citations:", len(context.get("citations", [])))
