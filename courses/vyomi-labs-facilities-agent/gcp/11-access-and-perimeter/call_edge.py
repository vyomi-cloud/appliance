import base64
import json

import requests

import gcp

URL = f"{gcp.ENDPOINT}/gcpgw/facilities-api-gw/search"
token = open("id_token.txt").read().strip()


def post(bearer):
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    return requests.post(URL, json={"query": "boiler pressure limit"}, headers=headers, timeout=60)


ok = post(token)
print("valid token:", ok.status_code, "| caller:", ok.json().get("caller"), "| results:", len(ok.json()["results"]))
print("no token:", post(None).status_code)
enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
forged = f"{enc({'alg': 'none'})}.{enc({'iss': 'https://securetoken.google.com/facilities-users', 'aud': 'facilities-users', 'email': 'evil@example.com'})}."
print("unsigned token:", post(forged).status_code)
assert ok.status_code == 200 and post(None).status_code in (401, 403) and post(forged).status_code in (401, 403)
