from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azdata import search_endpoint, search_key, INDEX

sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))
rows = list(sc.search(search_text="boiler pressure", select=["id", "source", "content"], top=3))
print("documents in the index:", len(list(sc.search(search_text="*", top=50))))
print("'boiler pressure' ->", rows[0]["source"])
