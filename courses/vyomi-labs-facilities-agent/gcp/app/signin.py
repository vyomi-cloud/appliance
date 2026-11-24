import base64
import json

import requests
from google.auth.transport import requests as grequests
from google.oauth2 import id_token

import gcp

USERS_PROJECT = "facilities-users"
EMAIL, PASSWORD = "maria.ops@example.com", "Fac!lities-2026"


def identity(op, body):
    r = requests.post(f"{gcp.ENDPOINT}/v1/accounts:{op}", params={"key": "vyomi-local"}, json=body, timeout=30, headers={"x-goog-user-project": USERS_PROJECT})
    if r.status_code != 200 and "EMAIL_EXISTS" not in r.text:
        raise RuntimeError(f"accounts:{op} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


identity("signUp", {"email": EMAIL, "password": PASSWORD, "returnSecureToken": True})
token = identity("signInWithPassword", {"email": EMAIL, "password": PASSWORD, "returnSecureToken": True})["idToken"]
open("id_token.txt", "w").write(token)
print("signed in; the ID token is a JWT with", token.count(".") + 1, "parts")

claims = id_token.verify_token(token, grequests.Request(), audience=USERS_PROJECT,
                               certs_url=f"{gcp.ENDPOINT}/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com")
print("verified: issuer", claims["iss"], "| audience", claims["aud"], "| email", claims["email"])
assert claims["email"] == EMAIL and claims["iss"] == f"https://securetoken.google.com/{USERS_PROJECT}"
