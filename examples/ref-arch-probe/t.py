import sys; sys.path.insert(0,".")
from _common import *
import base64, time
P=PROJECT; par=f"projects/{P}/locations/{LOC}"
call("POST",f"/v1/{par}/keyRings",{}, params={"keyRingId":"r1"})
call("POST",f"/v1/{par}/keyRings/r1/cryptoKeys",{"purpose":"ENCRYPT_DECRYPT"}, params={"cryptoKeyId":"k1"})
k=f"{par}/keyRings/r1/cryptoKeys/k1"
b=lambda x: base64.b64encode(x).decode()
e=call("POST",f"/v1/{k}:encrypt",{"plaintext":b(b"hello"),"additionalAuthenticatedData":b(b"a")})
r=http().post(endpoint()+f"/v1/{k}:decrypt",json={"ciphertext":e["ciphertext"],"additionalAuthenticatedData":b(b"WRONG")}); print("wrong aad",r.status_code,r.text[:150])
r=http().post(endpoint()+f"/v1/{k}:decrypt",json={"ciphertext":e["ciphertext"]}); print("no aad",r.status_code,r.text[:150])
ln=f'logName="projects/{P}/logs/cloudaudit.googleapis.com%2Factivity"'
for f in (ln, ln+' AND timestamp>="2026-11-17T00:00:00Z"', ln+' AND timestamp>="2026-11-17T00:00:00.000Z"', ln+' AND timestamp>"2026-11-17T00:00:00Z"'):
    r=call("POST","/v2/entries:list",{"resourceNames":[f"projects/{P}"],"filter":f})
    print(len(r.get("entries",[])), f[-45:], sorted({e.get("protoPayload",{}).get("methodName","") for e in r.get("entries",[])})[:6])
