import json, urllib.request, base64
EP="http://127.0.0.1:18741"
SUB="/subscriptions/00000000-0000-0000-0000-cloudlearn01"
def jwt(**c):
    e=lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return e({"alg":"none","typ":"JWT"})+"."+e(c)+".sig"
def call(method, path, body=None, oid=None, raw=None, hdr=None):
    h=dict(hdr or {})
    if oid: h["Authorization"]="Bearer "+jwt(oid=oid)
    data=raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if body is not None: h["Content-Type"]="application/json"
    r=urllib.request.Request(EP+path,data=data,method=method,headers=h)
    try:
        x=urllib.request.urlopen(r); return x.status, x.read().decode()[:350]
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:500]
def enf(**d): return call("PUT","/api/iam/azure/enforcement",body=d)
