import base64
import json
import requests
from azlab import ENDPOINT, TENANT, RG
from azdata import function_key
from entra import API_URI
from gw import apim, SERVICE, url, subscription_key

cfg = json.load(open("entra.json"))
POLICY = ('<policies><inbound><base/>'
          '<validate-jwt header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized. Access token is missing or invalid.">'
          f'<openid-config url="{ENDPOINT}/{TENANT}/v2.0/.well-known/openid-configuration"/>'
          f'<audiences><audience>{API_URI}</audience><audience>{cfg["client_id"]}</audience></audiences></validate-jwt>'
          f'<set-header name="x-functions-key" exists-action="override"><value>{function_key()}</value></set-header>'
          '<rate-limit-by-key calls="60" renewal-period="60" counter-key="@(context.Subscription.Id)"/>'
          '<set-header name="x-vyomi-caller" exists-action="override"><value>@(context.Request.Headers.GetValueOrDefault("Authorization","").AsJwt()?.Claims["azp"].FirstOrDefault())</value></set-header>'
          '</inbound><backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>')
apim().api_policy.create_or_update(RG, SERVICE, "tools", "policy", {"value": POLICY, "format": "xml"})


def call(key=True, token=None):
    h = {"Content-Type": "application/json"}
    if key:
        h["Ocp-Apim-Subscription-Key"] = subscription_key()
    if token:
        h["Authorization"] = "Bearer " + token
    return requests.post(url("tools/kb-search"), json={"query": "boiler pressure limit"}, headers=h, timeout=60)


b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
forged = f"{b64({'alg': 'none'})}.{b64({'aud': API_URI, 'appid': 'evil'})}."
print("no subscription key:", call(key=False, token=open("token.txt").read()).status_code)
print("key but no token:", call().status_code)
print("forged alg=none token:", call(token=forged).status_code)
good = call(token=open("token.txt").read())
print("real Entra user token:", good.status_code, "| results:", len(good.json()["results"]))
app_call = call(token=open("app_token.txt").read()).json()
print("application token -> caller seen by the tool is the app id:", app_call["caller"] == cfg["client_id"])
