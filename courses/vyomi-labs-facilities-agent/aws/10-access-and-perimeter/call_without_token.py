import json
import os
import urllib.error
import urllib.request

import boto3

api = next(a["id"] for a in boto3.client("apigateway").get_rest_apis()["items"] if a["name"] == "facilities-api")
url = os.environ["AWS_ENDPOINT_URL"].rstrip("/") + "/restapis/%s/prod/_user_request_/search" % api
req = urllib.request.Request(url, data=json.dumps({"query": "boiler pressure limit"}).encode(), method="POST", headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=60)
    raise AssertionError("an anonymous call was accepted by the API")
except urllib.error.HTTPError as e:
    print("anonymous call rejected with HTTP", e.code, "(401 or 403:", e.code in (401, 403), ")")
    assert e.code in (401, 403), "expected 401/403 for an anonymous call, got %d" % e.code
