import json

import boto3

oss = boto3.client("opensearchserverless")
oss.create_security_policy(name="facilities-enc", type="encryption", policy=json.dumps(
    {"Rules": [{"ResourceType": "collection", "Resource": ["collection/facilities-kb"]}], "AWSOwnedKey": True}))
c = oss.create_collection(name="facilities-kb", type="VECTORSEARCH")["createCollectionDetail"]
print("collection", c["name"], c["arn"])
