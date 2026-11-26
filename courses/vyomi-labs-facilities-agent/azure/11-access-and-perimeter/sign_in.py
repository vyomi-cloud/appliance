import json
import jwt
import requests
from azure.identity import ClientSecretCredential
from azlab import ENDPOINT, TENANT
from entra import API_URI, USER, PASSWORD

cfg = json.load(open("entra.json"))
cred = ClientSecretCredential(TENANT, cfg["client_id"], cfg["client_secret"], authority=ENDPOINT, disable_instance_discovery=True)
app_token = cred.get_token(API_URI + "/.default").token
open("app_token.txt", "w").write(app_token)
print("application token is a JWT:", app_token.count(".") == 2)

r = requests.post(f"{ENDPOINT}/{TENANT}/oauth2/v2.0/token", data={"grant_type": "password", "client_id": cfg["client_id"], "username": USER, "password": PASSWORD,
                                                                  "scope": API_URI + "/.default"}, timeout=30)
r.raise_for_status()
user_token = r.json()["access_token"]
open("token.txt", "w").write(user_token)

key = jwt.PyJWKClient(f"{ENDPOINT}/{TENANT}/discovery/v2.0/keys").get_signing_key_from_jwt(user_token).key
claims = jwt.decode(user_token, key, algorithms=["RS256"], audience=[API_URI, cfg["client_id"]], options={"verify_iss": False})
print("signature verified against the tenant keys | signed in as:", claims.get("preferred_username") or claims.get("upn"))
