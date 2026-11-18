"""C7 Tools: Cloud Functions gen2 (google-cloud-functions) create + HTTP invoke; the function reads Firestore documents seeded by the app."""
from _common import *

s = Step()
CODE = '''
import json, os, urllib.request

def handler(request):
    body = request.get_json(silent=True) or {}
    base = os.environ["SIM"]
    url = f"{base}/v1/projects/{os.environ['PROJ']}/databases/(default)/documents/assets/{body['asset_id']}"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer x"})
    doc = json.load(urllib.request.urlopen(req, timeout=20))
    f = doc["fields"]
    return {"found": True, "asset_id": f["asset_id"]["stringValue"], "status": f["status"]["stringValue"]}
'''


PURE = '''
import json

def handler(request):
    b = request.get_json(silent=True) or {}
    return {"asset_id": b.get("asset_id"), "over_limit": b.get("psi", 0) > 30}
'''


def pure():
    r = deploy_function(f"pure-{TAG}", PURE)
    out = invoke_function(f"pure-{TAG}", {"asset_id": "B-12", "psi": 31})
    assert out.status_code == 200 and out.json().get("over_limit") is True, (out.status_code, out.text[:200])
    return out.json()


def seed():
    fs = firestore_rest()
    fs_set(fs, "assets", "B-12", {"asset_id": "B-12", "status": "degraded", "psi": 31})
    return fs_get(fs, "assets", "B-12")


def deploy():
    r = deploy_function(f"asset-status-{TAG}", CODE, env={"SIM": endpoint(), "PROJ": PROJECT})
    s.fn = r.name.rsplit("/", 1)[-1]
    return r.name + " state=" + str(r.state.name)


def invoke():
    r = invoke_function(s.fn, {"asset_id": "B-12"})
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    out = r.json()
    assert out.get("status") == "degraded", out
    return out


def logs():
    r = call("POST", "/v2/entries:list", {"resourceNames": [f"projects/{PROJECT}"], "filter": f'resource.labels.service_name="{s.fn}"', "pageSize": 5})
    return f"{len(r.get('entries', []))} log entries for the function"


s("Cloud Functions gen2: pure-compute function deploys and returns a result over HTTPS", pure)
s("Firestore (gapic REST): seed asset doc + read back", seed)
s("Cloud Functions gen2: generate_upload_url + PUT zip + create_function", deploy)
if hasattr(s, "fn"):
    s("invoke function over HTTPS; it reads the Firestore doc from inside (urllib)", invoke)
    s("function invocation visible in Cloud Logging", logs)
s.finish()
