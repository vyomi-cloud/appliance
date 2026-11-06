"""Standalone: PYTHONPATH=. python tests/test_sandbox_access.py
Throwaway RSA key is injected through sandbox_access.JWKS_PROVIDER."""
import base64, json, os, sys, time, uuid
os.environ["CODESPACE_NAME"] = "fuzzy-cs-123"
os.environ.pop("VYOMI_SANDBOX_ACCESS", None)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from core import sandbox_access as sa

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
n = key.public_key().public_numbers()
b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
sa.JWKS_PROVIDER = lambda: {"keys": [{"kty": "RSA", "kid": "k", "alg": "RS256",
    "n": b64(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")), "e": b64(n.e.to_bytes(3, "big"))}]}

def mint(priv=key, **over):
    now = int(time.time())
    c = {"aud": "vyomi-sandbox-access", "cs": "fuzzy-cs-123", "grant": "g", "sub": "alice", "iat": now,
         "exp": now + 90, "jti": uuid.uuid4().hex, "name": "Alice <b>", "login": "alice",
         "email": "a@x.io", "avatar": "https://github.com/alice.png", "edition": "enterprise", "role": "admin"}
    c.update(over)
    h = b64(json.dumps({"alg": "RS256", "kid": "k"}).encode()); p = b64(json.dumps(c).encode())
    return f"{h}.{p}.{b64(priv.sign(f'{h}.{p}'.encode(), padding.PKCS1v15(), hashes.SHA256()))}"

async def ws(w):
    await w.accept(); await w.send_text("hi"); await w.close()
app = Starlette(routes=[Route("/", lambda r: PlainTextResponse("home")),
    Route("/healthz", lambda r: PlainTextResponse("ok")),
    Route("/api/x", lambda r: JSONResponse({"a": 1}), methods=["GET", "OPTIONS"]), WebSocketRoute("/ws", ws)])
sa.register(app)
PUB = "https://fuzzy-cs-123-9000.app.github.dev"
pub = lambda: TestClient(app, base_url=PUB, follow_redirects=False)
loc = lambda: TestClient(app, base_url="http://localhost:9000", follow_redirects=False)

ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

c = pub()
check("no cookie, API -> 401 json", c.get("/api/x").status_code == 401 and c.get("/api/x").json()["error"] == "sandbox_private")
r = c.get("/", headers={"accept": "text/html"})
check("no cookie, browser nav -> HTML 401", r.status_code == 401 and "text/html" in r.headers["content-type"] and "private" in r.text)
check("preflight not bypassed", c.options("/api/x", headers={"origin": "https://evil.io", "access-control-request-method": "GET"}).status_code == 401)
check("localhost open", loc().get("/").status_code == 200 and loc().get("/api/x").status_code == 200)
check("/healthz open on public host", c.get("/healthz").status_code == 200)
try:
    with c.websocket_connect("/ws", headers={"host": PUB[8:]}) as w: w.receive_text(); gated = False
except WebSocketDisconnect: gated = True
except Exception: gated = True
check("websocket gated", gated)
check("whoami unauthenticated", c.get("/api/sandbox/whoami").json() == {"authenticated": False})
check("whoami localhost", loc().get("/api/sandbox/whoami").json() == {"authenticated": False})

tok = mint()
r = c.get(f"/_vy/access?token={tok}")
sc = r.headers.get("set-cookie", "")
check("valid token -> 302 + cookie flags", r.status_code == 302 and r.headers["location"] == "/"
      and "vy_sbx=" in sc and "HttpOnly" in sc and "Secure" in sc and "SameSite=Lax" in sc)
check("cookie -> 200", c.get("/api/x").status_code == 200 and c.get("/").text == "home")
who = c.get("/api/sandbox/whoami").json()
check("whoami identity (sanitised)", who["authenticated"] and who["login"] == "alice" and who["role"] == "admin"
      and who["edition"] == "enterprise" and "<" not in who["name"] and who["avatar"].startswith("https://github.com/"))
with c.websocket_connect("/ws", headers={"host": PUB[8:], "cookie": "vy_sbx=" + sc.split("vy_sbx=")[1].split(";")[0]}) as w:
    check("websocket allowed with cookie", w.receive_text() == "hi")
check("replayed jti -> 403", pub().get(f"/_vy/access?token={tok}").status_code == 403)
check("wrong cs -> 403", pub().get(f"/_vy/access?token={mint(cs='other')}").status_code == 403)
check("expired -> 403", pub().get(f"/_vy/access?token={mint(iat=int(time.time())-300, exp=int(time.time())-200)}").status_code == 403)
check("wrong aud -> 403", pub().get(f"/_vy/access?token={mint(aud='cloudlearn-simulator')}").status_code == 403)
t = mint(); h, p, s = t.split(".")
check("tampered claims -> 403", pub().get(f"/_vy/access?token={h}.{b64(json.dumps({'aud':'vyomi-sandbox-access','cs':'fuzzy-cs-123','exp':int(time.time())+90,'iat':int(time.time()),'jti':'z','role':'admin'}).encode())}.{s}").status_code == 403)
check("foreign key -> 403", pub().get(f"/_vy/access?token={mint(priv=rsa.generate_private_key(public_exponent=65537, key_size=2048))}").status_code == 403)
check("garbage token -> 403", pub().get("/_vy/access?token=abc").status_code == 403)
bad = pub(); bad.cookies.set("vy_sbx", "x.y")
check("forged cookie -> 401", bad.get("/api/x").status_code == 401)
r = pub().get("/_vy/access?token=abc", headers={"accept": "text/html"})
check("403 page is HTML", "text/html" in r.headers["content-type"])
xf = TestClient(app, base_url="http://localhost:9000", follow_redirects=False)
check("X-Forwarded-Host public -> gated", xf.get("/api/x", headers={"x-forwarded-host": "fuzzy-cs-123-9000.app.github.dev"}).status_code == 401)
os.environ["VYOMI_SANDBOX_ACCESS"] = "off"
check("VYOMI_SANDBOX_ACCESS=off -> open", pub().get("/api/x").status_code == 200)
del os.environ["VYOMI_SANDBOX_ACCESS"]; os.environ.pop("CODESPACE_NAME")
check("no CODESPACE_NAME -> open", pub().get("/api/x").status_code == 200)
print("ALL PASS" if ok else "FAILURES"); sys.exit(0 if ok else 1)
