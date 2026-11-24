import json
import os
import urllib.request

import boto3

cg, ag = boto3.client("cognito-idp"), boto3.client("apigateway")
pool = next(p["Id"] for p in cg.list_user_pools(MaxResults=20)["UserPools"] if p["Name"] == "facilities-users")
cid = cg.list_user_pool_clients(UserPoolId=pool)["UserPoolClients"][0]["ClientId"]
token = cg.initiate_auth(ClientId=cid, AuthFlow="USER_PASSWORD_AUTH",
                         AuthParameters={"USERNAME": "maria.ops@example.com", "PASSWORD": "Fac!lities-2026"})["AuthenticationResult"]["IdToken"]
api = next(a["id"] for a in ag.get_rest_apis()["items"] if a["name"] == "facilities-api")
url = os.environ["AWS_ENDPOINT_URL"].rstrip("/") + "/restapis/%s/prod/_user_request_/search" % api
req = urllib.request.Request(url, data=json.dumps({"query": "boiler pressure limit"}).encode(), method="POST",
                             headers={"Content-Type": "application/json", "Authorization": token})
with urllib.request.urlopen(req, timeout=60) as r:
    body = json.loads(r.read())
print("HTTP", r.status, "| results:", len(body["results"]), "| top source:", body["results"][0]["source"])
