"""Booster remote-LLM spike, hermetic: fake llama.cpp servers (this process) <- REAL docker/booster-runner-llm/runner-llm-dial.mjs
(the runner) <- REAL wasm/relay/local-relay.mjs (hub, /llm-runner + /llm) <- core.booster_llm_gateway (remote mode) <- core.llm_core.

Covers: attach/detach, capacity not reserving the AI bucket, runner drop -> honest 503, no local fallback, token auth on the
dial-in (role-scoped), TTL expiry (runner TTL_S and token session_end), no token in runner logs. No GitHub, no Docker.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_booster_remote_llm.py   (needs node + the `ws` package)
"""
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="booster-remote-llm-"))
os.environ["VYOMI_HOST_MEM_MB"] = "8000"            # 2-core/8 GB Codespace: cap 5600 -> local AI share 2800
os.environ.pop("VYOMI_BOOSTER_CAP_MB", None)
os.environ.pop("VYOMI_LLM_ENDPOINT", None)
os.environ.pop("VYOMI_BOOSTER_REMOTE_LLM", None)
os.environ.pop("VYOMI_BOOSTER_REMOTE_LLM_FALLBACK", None)
KEY = "remote-llm-test-key-0123456789"
os.environ["VYOMI_BOOSTER_SESSION_KEY"] = KEY
os.environ["VYOMI_BOOSTER"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


node = shutil.which("node")
ws_pkg = os.environ.get("WS_PKG") or next(iter(
    glob.glob(os.path.expanduser("~/.npm/_npx/*/node_modules/ws")) + glob.glob(os.path.join(ROOT, "wasm", "**", "node_modules", "ws"), recursive=True)), "")
if not node or not ws_pkg:
    print("[SKIP] node or the `ws` package not found (set WS_PKG): remote LLM relay tests need them")
    sys.exit(0)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


# ---- fake llama.cpp (chat on one port, embeddings on another) ---------------------------------------------------------
class Fake(BaseHTTPRequestHandler):
    kind = "chat"
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        b = b'{"status":"ok"}'
        self.send_response(200); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        Fake.seen.append((self.kind, self.path, body))
        if self.kind == "embed":
            out = json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}], "model": body.get("model")}).encode()
        elif body.get("stream"):
            self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
            for t in ("he", "llo"):
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) + "\n\n").encode()); self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
            return
        else:
            out = json.dumps({"choices": [{"message": {"role": "assistant", "content": "hello from the runner"}, "finish_reason": "stop"}],
                              "usage": {"prompt_tokens": 3, "completion_tokens": 4}, "model": body.get("model")}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out))); self.end_headers()
        self.wfile.write(out)


def start_fake(kind):
    h = type("F", (Fake,), {"kind": kind})
    srv = ThreadingHTTPServer(("127.0.0.1", free_port()), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


chat, emb = start_fake("chat"), start_fake("embed")

# ---- the relay (hub) ---------------------------------------------------------------------------------------------------
RELAY = free_port()
relay = subprocess.Popen([node, os.path.join(ROOT, "wasm", "relay", "local-relay.mjs")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env={**os.environ, "RELAY_PORT": str(RELAY), "RELAY_HOST": "127.0.0.1", "WS_PKG": ws_pkg,
                              "VYOMI_LLM_HB_STALE_MS": "4000"})
HUB = f"http://127.0.0.1:{RELAY}"
for _ in range(60):
    try:
        urllib.request.urlopen(HUB + "/health", timeout=1); break
    except Exception:
        time.sleep(0.1)

runners = []


def cleanup():
    for r in runners:
        try: r.kill()
        except Exception: pass
    try: relay.kill()
    except Exception: pass


import atexit  # noqa: E402
atexit.register(cleanup)

from core import booster_session as BS  # noqa: E402

SID = "sess-llm-1"
now = int(time.time())


def tok(role="", end=None, key=KEY, sid=SID, sub="acct-1"):
    return BS.mint(sub, "pro", end or now + 3600, primary_cloud="aws", session_id=sid, key=key, role=role)


BOOSTER_TOKEN = tok()
RUNNER_TOKEN = tok("llm-runner")
os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = BOOSTER_TOKEN


def start_runner(token=RUNNER_TOKEN, ttl=None):
    env = {**os.environ, "VYOMI_RELAY_URL": HUB.replace("http", "ws") + "/llm-runner", "VYOMI_RUNNER_TOKEN": token, "WS_PKG": ws_pkg,
           "CHAT_URL": f"http://127.0.0.1:{chat.server_address[1]}", "EMBED_URL": f"http://127.0.0.1:{emb.server_address[1]}"}
    if ttl:
        env["TTL_S"] = str(ttl)
    p = subprocess.Popen([node, os.path.join(ROOT, "docker", "booster-runner-llm", "runner-llm-dial.mjs")], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    runners.append(p)
    return p


def http(method, url, headers=None, body=None, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def wait(cond, secs=12):
    t = time.time()
    while time.time() - t < secs:
        if cond():
            return True
        time.sleep(0.1)
    return False


def dial_status(headers):
    """Raw WS handshake against /llm-runner; returns the HTTP status (101 = accepted)."""
    s = socket.create_connection(("127.0.0.1", RELAY), timeout=5)
    h = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    s.sendall((f"GET /llm-runner HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n{h}\r\n").encode())
    line = s.recv(200).split(b"\r\n")[0].decode()
    s.close()
    return int(line.split()[1])


# ---- booster side ------------------------------------------------------------------------------------------------------
from core import booster as B  # noqa: E402
from core import booster_ai as AI  # noqa: E402
from core import booster_remote_llm as R  # noqa: E402
from core import llm_core  # noqa: E402

# 0. OFF by default
try:
    R.attach(HUB, BOOSTER_TOKEN); ok = False
except R.RemoteLLMError as e:
    ok = e.code == "remote_llm_disabled"
check("OFF by default: attach refused without VYOMI_BOOSTER_REMOTE_LLM=1", ok)
check("OFF by default: status says local", R.info()["mode"] == "local" and B._llm_label() == "llm: local (booster)", R.info())

os.environ["VYOMI_BOOSTER_REMOTE_LLM"] = "1"

# baseline: the local AI pack reserves its bucket
AI.admit_configured(enforce=True)
used_before = B.usage()["ai"]
bud_before = B.resource_budget()["memory_split_mb"]
check("baseline: local pack reserves the AI bucket (3B + bge)", used_before >= 2500 and bud_before["ai"] == 2800, (used_before, bud_before))

# 1. attach: pack released, bucket not reserved, whole cap to compute
info = R.attach(HUB, BOOSTER_TOKEN)
bud = B.resource_budget()["memory_split_mb"]
check("attach: reports mode remote / label 'llm: remote (runner)'", info["attached"] and info["mode"] == "remote" and B._llm_label().startswith("llm: remote (runner)"), info)
check("attach: local AI reservations released", B.usage()["ai"] == 0, B.usage())
check("attach: AI bucket is 0 and compute gets the whole cap (RAM saved)", bud["ai"] == 0 and bud["compute"] == bud_before["compute"] + bud_before["ai"], bud)
try:
    AI.admit("qwen2.5-3b", "chat", enforce=True); ok = False
except AI.ModelAdmissionError as e:
    ok = e.code == "remote_llm_attached"
check("attach: admitting the local 3B model is refused (pack does not load)", ok and B.usage()["ai"] == 0)
pl = AI.admit_configured(enforce=True)
check("attach: admit_configured reserves nothing; plan tells the boot script to start no model servers",
      B.usage()["ai"] == 0 and pl["ok"] is False and pl["chat"] is None and pl.get("remote") is True, pl)
check("attach: llm_core points at the loopback gateway, not the in-pack gateway", llm_core._endpoint().startswith("http://127.0.0.1:") and AI.point_llm_at_gateway() == llm_core._endpoint())

# 2. no runner yet -> honest 503, nothing local started
def chat_req(stream=False):
    return http("POST", llm_core._endpoint() + "/v1/chat/completions", body={"model": "qwen2.5-3b", "messages": [{"role": "user", "content": "hi"}], "stream": stream})

code, body, _ = chat_req()
check("runner absent: 503 RunnerNotLinked (not a hang, not a local answer)", code == 503 and b"RunnerNotLinked" in body, (code, body[:120]))
check("runner absent: nothing was served locally and AI bucket still 0", not Fake.seen and B.usage()["ai"] == 0)
st = AI.status()
check("status: AI chip reports remote (runner) + unavailable while the runner is absent", st["backend"] == "remote-runner" and st["state"] == "unavailable" and "remote (runner)" in st["chip"], st)

# 3. token auth on the dial-in
check("dial-in: a BOOSTER token cannot pose as the runner (403)", dial_status({"Authorization": f"Bearer {BOOSTER_TOKEN}"}) == 403)
check("dial-in: bad signature refused (401)", dial_status({"Authorization": f"Bearer {tok('llm-runner', key='another-key-entirely-0123456789')}"}) == 401)
check("dial-in: missing token refused (401)", dial_status({}) == 401)
check("dial-in: expired runner token refused (410)", dial_status({"Authorization": "Bearer " + BS.mint("acct-1", "pro", now - 5, session_id=SID, key=KEY, role="llm-runner", now=now - 100)}) == 410)
code, _, _ = http("POST", HUB + "/llm/v1/chat/completions", {"x-vyomi-session-token": RUNNER_TOKEN}, {"a": 1})
check("llm plane: a RUNNER token cannot call the LLM plane (403)", code == 403, code)
code, _, _ = http("POST", HUB + "/llm/v1/chat/completions", {"x-vyomi-session-token": tok(sub="someone-else", sid="other")}, {"a": 1})
check("llm plane: another session sees no runner (502, never ours)", code == 502, code)
code, _, _ = http("POST", HUB + "/llm/v1/chat/completions", None, {"a": 1})
check("llm plane: no token refused (401)", code == 401, code)
try:
    BS.mint("a", "pro", now + 60, session_id="s", key=KEY, role="llm-runner")
    err = BS.authorise({"x-vyomi-session-token": RUNNER_TOKEN}, "/anything", "aws")
    ok = err is not None and err.code == "BoosterSessionWrongRole"
except Exception as e:
    ok = False
check("booster API: a runner-role token never authorises booster calls", ok)

# 4. a real runner dials in -> ready -> chat/stream/embeddings flow
r1 = start_runner()
check("runner dials out and becomes ready", wait(lambda: (R._PROBE.update(at=0.0), R.runner_state())[1] == "ready"), R.runner_state())
code, body, _ = chat_req()
j = json.loads(body) if code == 200 else {}
check("chat completion round-trips through the relay to the runner", code == 200 and j["choices"][0]["message"]["content"] == "hello from the runner", (code, body[:120]))
res = llm_core.chat([{"role": "user", "content": "hi"}], None, 16, 0.0, None)
check("llm_core.chat (the seam the cloud wires use) works against the remote LLM", res is not None and "hello from the runner" in json.dumps(res, default=str), res)
code, body, h = chat_req(stream=True)
check("SSE streaming passes through chunk by chunk", code == 200 and b"he" in body and b"[DONE]" in body, body[:120])
code, body, _ = http("POST", llm_core._endpoint() + "/v1/embeddings", body={"model": "qwen2.5-3b", "input": "x"})
check("embeddings routed to the runner's embed server with model rewritten", code == 200 and any(k == "embed" and b.get("model") == "embed" for k, _, b in Fake.seen), Fake.seen[-1:])
check("status: ready, 'llm: remote (runner)', AI bucket still 0", AI.status()["state"] == "ready" and B.status()["llm"] == "llm: remote (runner)" and B.usage()["ai"] == 0, B.status()["llm"])

# 5. runner drop -> honest 503; no local fallback
r1.kill(); r1.wait()
out1 = r1.stdout.read()
check("runner log never contains the token, relay URL secrets or request text", RUNNER_TOKEN not in out1 and "hello" not in out1 and "linked to relay" in out1, out1[-200:])
check("runner drop: next call is 503 (RunnerNotLinked)", wait(lambda: chat_req()[0] == 503, 8))
code, body, _ = chat_req()
check("runner drop: error names the runner, no hang", code == 503 and b"remote LLM runner unavailable" in body, (code, body[:160]))
n = len(Fake.seen)
chat_req(); AI.admit_configured(enforce=True)
check("runner drop: the in-Codespace AI pack did NOT start (no reservation, no local answer)", B.usage()["ai"] == 0 and len(Fake.seen) == n and AI.plan()["chat"] is None)

# 6. runner TTL expiry (entrypoint TTL_S) exits cleanly 0 and the hub stops serving
r2 = start_runner(ttl=2)
check("TTL: runner ready", wait(lambda: (R._PROBE.update(at=0.0), R.runner_state())[1] == "ready"))
try:
    rc = r2.wait(timeout=8)
except subprocess.TimeoutExpired:
    rc = None
check("TTL: runner exits 0 at TTL_S", rc == 0, rc)
out2 = r2.stdout.read() if r2.stdout else ""
check("TTL: runner log says ttl and has no token", "ended: ttl" in out2 and RUNNER_TOKEN not in out2, out2[-200:])
check("TTL: after the runner exits the booster gets 503", wait(lambda: chat_req()[0] == 503, 8))

# 7. session_end expiry on the hub side drops the runner and the plane answers 410->503
end = int(time.time()) + 3
sid2 = "sess-llm-2"
os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = tok(sid=sid2, end=end)
R.attach(HUB, os.environ["VYOMI_BOOSTER_SESSION_TOKEN"])
r3 = start_runner(token=tok("llm-runner", sid=sid2, end=end))
check("session_end: runner ready", wait(lambda: (R._PROBE.update(at=0.0), R.runner_state())[1] == "ready"))
check("session_end: serving before the end", chat_req()[0] == 200)
time.sleep(max(0, end - time.time()) + 1.2)
code, body, _ = chat_req()
check("session_end: after the session ended the plane refuses -> 503", code == 503, (code, body[:120]))
check("session_end: runner process exits by itself", r3.poll() is not None or wait(lambda: r3.poll() is not None, 5))

# 8. detach: gateway closed; local pack stays OFF unless configured
os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = BOOSTER_TOKEN
R.attach(HUB, BOOSTER_TOKEN)
ep = llm_core._endpoint()
d = R.detach()
check("detach: mode back to local, bucket restored", d["mode"] == "local" and B.resource_budget()["memory_split_mb"]["ai"] == 2800, d)
try:
    urllib.request.urlopen(ep + "/health", timeout=2); ok = False
except Exception:
    ok = True
check("detach: gateway is closed - no silent fallback to a local model", ok and B.usage()["ai"] == 0 and AI.plan()["chat"] is None)
os.environ["VYOMI_BOOSTER_REMOTE_LLM_FALLBACK"] = "local"
R.attach(HUB, BOOSTER_TOKEN); R.detach()
check("detach with VYOMI_BOOSTER_REMOTE_LLM_FALLBACK=local: pack re-admitted (explicit opt-in only)", B.usage()["ai"] >= 2500, B.usage())

cleanup()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
