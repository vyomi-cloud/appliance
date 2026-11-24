from google.api_core import exceptions as gex

import gcp
from docs import DOCS

client = gcp.storage_client()
try:
    bucket = client.create_bucket("facilities-docs")
except gex.Conflict:
    bucket = client.bucket("facilities-docs")
for name, text in DOCS.items():
    bucket.blob("docs/" + name).upload_from_string(text.encode(), content_type="text/markdown")
print(f"{len(DOCS)} documents uploaded to gs://facilities-docs/docs/")
