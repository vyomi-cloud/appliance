import time
import uuid
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
from azdata import search_endpoint, search_key, storage_cs, INDEX

word = "zebrafish" + uuid.uuid4().hex[:6]
BlobServiceClient.from_connection_string(storage_cs("Blob")).get_blob_client("docs", "water-leak-sop.md").upload_blob(
    f"# SOP-205 Water leak\nReport a {word} water leak in the lobby to facilities immediately.".encode(), overwrite=True)
sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))
found = []
for _ in range(45):
    found = [r["source"] for r in sc.search(search_text=word, select=["source"], top=3)]
    if found:
        break
    time.sleep(1)
print("new upload became searchable as:", found[0] if found else "NOT FOUND")
