import json, urllib.request, base64, sys
EP="http://127.0.0.1:18741"
def jwt(email):
    e=lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return e({"alg":"none","typ":"JWT"})+"."+e({"email":email})+".sig"
def call(method, path, body=None, email=None, raw=None, ctype="application/json"):
    h={}
    if email: h["Authorization"]="Bearer "+jwt(email)
    data=raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None: h["Content-Type"]=ctype
    r=urllib.request.Request(EP+path,data=data,method=method,headers=h)
    try:
        x=urllib.request.urlopen(r); return x.status, x.read().decode()[:300]
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:400]
def enf(**d): return call("PUT","/api/iam/gcp/enforcement",d)
