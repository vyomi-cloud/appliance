import json
import requests
from azlab import ENDPOINT

API_URI = "api://facilities-api"
USER, PASSWORD = "maria.ops@facilities.example.com", "Fac!lities-2026"


def graph(method, path, body=None):
    r = requests.request(method, f"{ENDPOINT}/v1.0{path}", json=body, headers={"Authorization": "Bearer vyomi-local"}, timeout=30)
    if r.status_code >= 300 and "already exists" not in r.text.lower():
        raise RuntimeError(f"Graph {method} {path} HTTP {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}


if __name__ == "__main__":
    app = graph("POST", "/applications", {"displayName": "facilities-users", "identifierUris": [API_URI]})
    secret = graph("POST", f"/applications/{app['id']}/addPassword", {"passwordCredential": {"displayName": "facilities-agent"}})
    graph("POST", "/users", {"displayName": "Maria Ops", "userPrincipalName": USER, "mailNickname": "maria.ops", "accountEnabled": True,
                             "passwordProfile": {"password": PASSWORD, "forceChangePasswordNextSignIn": False}})
    json.dump({"client_id": app["appId"], "client_secret": secret["secretText"]}, open("entra.json", "w"))
    print("app registration facilities-users client_id:", app["appId"], "| user:", USER)
