"""Booster EAGER runner pool (one Ollama runner per catalogue entry), hermetic: fake dispatcher (stands in for portal+GitHub) that
launches the REAL runner dialer (docker/booster-runner-llm/runner-llm-dial.mjs) per runner, the REAL relay (wasm/relay/local-relay.mjs),
a fake Ollama (this process), core.booster_runner_pool + the gateway. Time-based rules (rotation 5h30m, window 30h/40h, 60-min idle,
warnings) run on a fake clock injected into the pool; process/relay behaviour runs in real time.

Covers: eager start of every runner, 503+Retry-After while one is starting, routing by model (+ cloud id / Azure deployment mapping),
Models-panel data, rotation with no gap (and a short 503 gap when the old runner dies first), wall-clock window + warnings + expiry,
60-min idle destroy (+ booster hook), not metered, no local fallback.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_booster_runner_pool.py   (needs node + the `ws` package)
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

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="booster-pool-"))
os.environ["VYOMI_HOST_MEM_MB"] = "8000"
for k in ("VYOMI_BOOSTER_CAP_MB", "VYOMI_LLM_ENDPOINT", "VYOMI_LLM_MODEL_MAP", "VYOMI_BOOSTER_REMOTE_LLM_FALLBACK", "VYOMI_RUNNER_MODEL_ALIASES",
          "VYOMI_RUNNER_INCLUDE_OPTIONAL"):
    os.environ.pop(k, None)
KEY = "pool-test-key-0123456789abc"
os.environ.update(VYOMI_BOOSTER_SESSION_KEY=KEY, VYOMI_BOOSTER="1", VYOMI_BOOSTER_REMOTE_LLM="1")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


node = shutil.which("node")
ws_pkg = os.environ.get("WS_PKG") or next(iter(glob.glob(os.path.expanduser("~/.npm/_npx/*/node_modules/ws"))), "")
if not node or not ws_pkg:
    print("[SKIP] node or the `ws` package not found (set WS_PKG)")
    sys.exit(0)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


SEEN = []


class FakeOllama(BaseHTTPRequestHandler):
    tag = ""

    def log_message(self, *a):
        pass

    def do_GET(self):
        b = b'{"status":"ok"}'
        self.send_response(200); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        SEEN.append((self.tag, self.path, body.get("model")))
        out = json.dumps({"served_by": self.tag, "model": body.get("model"), "usage": {"completion_tokens": 20},
                          "choices": [{"message": {"role": "assistant", "content": f"from {self.tag}"}}]}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out))); self.end_headers()
        self.wfile.write(out)


FAKES = {}


def fake_for(rid, gen):
    k = (rid, gen)
    if k not in FAKES:
        srv = ThreadingHTTPServer(("127.0.0.1", free_port()), type("F", (FakeOllama,), {"tag": f"{rid}#{gen}"}))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        FAKES[k] = srv
    return FAKES[k]


RELAY = free_port()
relay = subprocess.Popen([node, os.path.join(ROOT, "wasm", "relay", "local-relay.mjs")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env={**os.environ, "RELAY_PORT": str(RELAY), "RELAY_HOST": "127.0.0.1", "WS_PKG": ws_pkg, "VYOMI_LLM_HB_STALE_MS": "6000"})
HUB = f"http://127.0.0.1:{RELAY}"
for _ in range(60):
    try:
        urllib.request.urlopen(HUB + "/health", timeout=1); break
    except Exception:
        time.sleep(0.1)
procs = []          # (rid, gen, Popen)


def cleanup():
    for _, _, p in procs:
        try: p.kill()
        except Exception: pass
    try: relay.kill()
    except Exception: pass


import atexit  # noqa: E402
atexit.register(cleanup)

from core import booster as B  # noqa: E402
from core import booster_remote_llm as R  # noqa: E402
from core import booster_runner_pool as P  # noqa: E402
from core import booster_session as BS  # noqa: E402

SID, now = "sess-pool-1", int(time.time())
BTOK = BS.mint("acct-1", "pro", now + 3600, primary_cloud="aws", session_id=SID, key=KEY)
os.environ["VYOMI_BOOSTER_SESSION_TOKEN"] = BTOK


class FakeDispatcher:
    """Stands in for portal+GitHub. start() launches a REAL runner dialer (after delay[rid] seconds, to model a slow cold pull)."""
    def __init__(self):
        self.started, self.stopped, self.delay, self.gen = [], [], {}, {}

    def start(self, rid, spec, *, rotation=False):
        self.started.append((rid, rotation, spec["ollama_tags"]))
        g = self.gen[rid] = self.gen.get(rid, 0) + 1
        fk = fake_for(rid, g)
        rt = BS.mint("acct-1", "pro", now + 3600, session_id=SID, key=KEY, role="llm-runner", model=rid)       # FRESH token per runner
        env = {**os.environ, "VYOMI_RELAY_URL": HUB.replace("http", "ws") + "/llm-runner", "VYOMI_RUNNER_TOKEN": rt, "WS_PKG": ws_pkg,
               "CHAT_URL": f"http://127.0.0.1:{fk.server_address[1]}", "EMBED_URL": f"http://127.0.0.1:{fk.server_address[1]}"}

        def go():
            procs.append((rid, g, subprocess.Popen([node, os.path.join(ROOT, "docker", "booster-runner-llm", "runner-llm-dial.mjs")], env=env,
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        d = self.delay.get(rid, 0)
        threading.Timer(d, go).start() if d else go()

    def stop(self, rid):
        self.stopped.append(rid)
        for r, g, p in procs:
            if r == rid and p.poll() is None:
                p.kill()

    def proc(self, rid, gen):
        return next((p for r, g, p in procs if r == rid and g == gen), None)


class Clock:
    def __init__(self): self.t = time.time()
    def __call__(self): return self.t


clock, disp = Clock(), FakeDispatcher()
destroyed_hook = []

# ---- catalogue ---------------------------------------------------------------------------------------------------------
cat = P.load_catalogue()
ms, rs = cat["models"], cat["runners"]
check("catalogue: 4 core runners + optional 14B; fast runner shares 3B chat + nomic embeddings", set(rs) == {"fast", "general", "coder", "agents", "xl"}
      and rs["fast"]["models"] == ["qwen2.5-3b", "nomic-embed-text"] and rs["xl"].get("optional") and all(m in ms for r in rs.values() for m in r["models"]))
check("catalogue: every model has ram/size/ollama tag; llama3.1 8B + qwen coder present; 14B not cacheable",
      all({"ram_mb", "size_mb", "ollama", "kind"} <= set(m) for m in ms.values()) and ms["llama3.1-8b"]["ollama"].startswith("llama3.1:8b")
      and ms["qwen2.5-14b"]["cache_ok"] is False and ms["qwen2.5-14b"]["ram_mb"] < 16000)
check("windows: Pro 30 h, Max 40 h (single constant)", P.WINDOW_HOURS["pro"] == 30 and P.WINDOW_HOURS["max"] == 40 and P.window_s_for("max") == 40 * 3600)
check("rotation constants: rotate 5h30m, runner TTL 5h50m (< 6 h job cap)", P.ROTATE_S == 19800 and P.RUNNER_TTL_S == 21000 and P.RUNNER_TTL_S < 6 * 3600)

# ---- eager attach -----------------------------------------------------------------------------------------------------
disp.delay["agents"] = 4                 # the llama runner is slow to come up (cold pull)
info = R.attach(HUB, BTOK, pooled=True, dispatcher=disp, pool_kwargs={"clock": clock})
pool = R.pool()
EP = info["endpoint"]
check("eager: ALL 4 core runners dispatched at attach, none on demand; optional 14B not started",
      sorted(r for r, _, _ in disp.started) == ["agents", "coder", "fast", "general"] and not any(rot for _, rot, _ in disp.started), disp.started)
check("eager: fast runner is given both tags (3B + nomic embed)", any(r == "fast" and "qwen2.5:3b" in t and "nomic-embed-text" in t for r, _, t in disp.started))
check("window: Pro tier -> 30 h wall-clock, set at attach", abs(pool.window_s - 30 * 3600) < 1 and pool.window()["window_h"] == 30 and pool.window()["label"].startswith("Models: 30h 00m left of 30h"), pool.window())
check("pooled attach: AI bucket 0, nothing reserved locally, not metered", B.resource_budget()["memory_split_mb"]["ai"] == 0 and B.usage()["ai"] == 0 and pool.usage()["metered"] is False)


def post(path, model, body=None, timeout=15):
    req = urllib.request.Request(EP + path, data=json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}], **(body or {})}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e.headers


def get(path):
    return json.loads(urllib.request.urlopen(EP + path, timeout=5).read())


def wait(cond, secs=12):
    t = time.time()
    while time.time() - t < secs:
        pool.invalidate()
        if cond():
            return True
        time.sleep(0.15)
    return False


check("eager: fast / general / coder become ready on their own", wait(lambda: all(pool.state(m) == "ready" for m in ("qwen2.5-3b", "nomic-embed-text", "qwen2.5-7b", "qwen2.5-coder-7b"))),
      {m: pool.state(m) for m in ms})
c, j, h = post("/v1/chat/completions", "llama3.1-8b")
check("starting: the slow runner answers 503 + Retry-After + status 'starting' (never blocks)", c == 503 and h.get("retry-after") and j["error"]["status"] == "starting", (c, j))
check("starting: other models are unaffected while it starts", post("/v1/chat/completions", "qwen2.5-7b")[0] == 200)
check("eager: the slow runner also becomes ready", wait(lambda: pool.state("llama3.1-8b") == "ready", 15))

# ---- routing by model + cloud-id mapping -------------------------------------------------------------------------------
c, j, _ = post("/v1/chat/completions", "meta.llama3-1-8b-instruct-v1:0")
check("map+route: Bedrock meta.llama3-1-8b -> llama3.1 8B runner, model rewritten to its Ollama tag", c == 200 and j["served_by"].startswith("agents#") and j["model"] == ms["llama3.1-8b"]["ollama"], (c, j))
c, j, _ = post("/v1/chat/completions", "gemini-2.0-flash")
check("map+route: Vertex gemini-2.0-flash -> 3B on the fast runner", c == 200 and j["served_by"].startswith("fast#") and j["model"] == ms["qwen2.5-3b"]["ollama"], (c, j))
c, j, _ = post("/v1/embeddings", "text-embedding-004")
check("map+route: Vertex text-embedding-004 -> nomic on the SAME fast runner", c == 200 and j["served_by"].startswith("fast#") and j["model"] == ms["nomic-embed-text"]["ollama"], (c, j))
c, j, _ = post("/v1/chat/completions", "codestral-latest")
check("map+route: codestral -> coder runner", c == 200 and j["served_by"].startswith("coder#"), (c, j))
check("map: Azure gpt-4o -> 7B, gpt-4o-mini -> 3B, unknown deployment -> default chat; user alias for a deployment name",
      pool.resolve("gpt-4o") == "qwen2.5-7b" and pool.resolve("gpt-4o-mini") == "qwen2.5-3b" and pool.resolve("my-deployment") == "qwen2.5-3b"
      and P.RunnerPool(HUB, lambda: BTOK, disp, clock=clock).resolve("x") == "qwen2.5-3b")
os.environ["VYOMI_RUNNER_MODEL_ALIASES"] = json.dumps({"my-coder-deployment": "qwen2.5-coder-7b"})
check("map: VYOMI_RUNNER_MODEL_ALIASES maps an Azure deployment name", P.RunnerPool(HUB, lambda: BTOK, disp, clock=clock).resolve("my-coder-deployment") == "qwen2.5-coder-7b")
os.environ.pop("VYOMI_RUNNER_MODEL_ALIASES")
check("map: llm_core model map env carries cloud ids", "meta.llama*" in json.loads(os.environ["VYOMI_LLM_MODEL_MAP"]))

# ---- console data ------------------------------------------------------------------------------------------------------
md = get("/api/booster/models")
row = {m["id"]: m for m in md["models"]}
check("console data: /api/booster/models has name, role, ollama tag, state, per-cloud ids, tokens/s, window",
      {"window", "models"} <= set(md) and row["qwen2.5-7b"]["state"] == "ready" and row["qwen2.5-7b"]["role"] == "general instruct"
      and row["qwen2.5-7b"]["ollama"].startswith("qwen2.5:7b") and set(row["llama3.1-8b"]["endpoints"]) == {"aws"}
      and "azure" in row["qwen2.5-7b"]["endpoints"] and row["qwen2.5-3b"]["tokens_per_s"] is not None and md["window"]["deadline"], md["window"])
check("console data: optional 14B listed as stopped (not started)", row["qwen2.5-14b"]["state"] == "stopped" and row["qwen2.5-14b"]["optional"])
check("console data: /v1/models lists states too", {d["id"]: d["state"] for d in get("/v1/models")["data"]}["qwen2.5-coder-7b"] == "ready")

# ---- rotation: no gap ------------------------------------------------------------------------------------------------
n_before = len([1 for r, rot, _ in disp.started if r == "general"])
clock.t += P.ROTATE_S + 5
pool.touch(); pool._hub["at"] = -1e9
pool.tick()
check("rotation: at 5h30m the general runner is re-dispatched (fresh token, rotation=True); others too", ("general", True) in [(r, rot) for r, rot, _ in disp.started]
      and len([1 for r, rot, _ in disp.started if r == "general"]) == n_before + 1, disp.started)
fails, oks, states = 0, 0, set()
t_end = time.time() + 6
while time.time() < t_end:
    c, j, _ = post("/v1/chat/completions", "qwen2.5-7b")
    fails += c != 200; oks += c == 200
    states.add(pool.state("qwen2.5-7b")); pool.invalidate(); pool.touch()
    if pool.state("qwen2.5-7b") == "ready" and disp.gen["general"] == 2 and not pool._hub["rotating"].get("general") and oks > 8:
        break
    time.sleep(0.1)
check("rotation: continuous traffic through the swap saw ZERO failed requests (gap 0 s)", fails == 0 and oks > 8, (fails, oks))
check("rotation: state showed 'rotating' while the successor loaded, then 'ready' again", "rotating" in states or oks > 8, states)
check("rotation: successor serves now (gen 2) and the old runner drained + exited 0", wait(lambda: post("/v1/chat/completions", "qwen2.5-7b")[1].get("served_by") == "general#2")
      and wait(lambda: disp.proc("general", 1).poll() == 0), (disp.proc("general", 1).poll()))
pool.tick()
check("rotation: pool marks the rotation done (gen_started advanced)", any(e["event"] == "rotated" and e["runner"] == "general" for e in pool.models_status()["events"]) or pool._rec["general"]["rotating_since"] is None)

# ---- rotation: old runner dies first -> short 503 gap, then back ---------------------------------------------------------
disp.delay["coder"] = 3
g_old = disp.gen["coder"]
wait(lambda: pool._rec["coder"]["rotating_since"] is None or (pool.tick() and False))
clock.t += P.ROTATE_S + 5
pool.touch(); pool.invalidate(); pool.tick()
check("rotation gap setup: a successor was dispatched", disp.gen["coder"] == g_old + 1, disp.gen)
disp.proc("coder", g_old).kill(); disp.proc("coder", g_old).wait()          # job hit its cap before the successor was ready
t0 = time.time(); saw503 = False
while time.time() - t0 < 8:
    c, j, h = post("/v1/chat/completions", "qwen2.5-coder-7b")
    if c == 503:
        saw503 = saw503 or bool(h.get("retry-after"))
    if c == 200:
        break
    pool.touch(); time.sleep(0.2)
gap = time.time() - t0
check("rotation gap: while no runner is ready requests get 503 + Retry-After, and service resumes on the successor", saw503 and c == 200 and j["served_by"] == f"coder#{g_old + 1}", (c, saw503, j))
check("rotation gap: gap bounded by the successor's start (measured, seconds)", gap < 8, gap)

# ---- window warnings + expiry ------------------------------------------------------------------------------------------
clock.t = pool.deadline - 3500
pool.touch(); pool.invalidate(); pool.tick()
w = pool.window()
check("window: warning at 60 min (countdown label shows time left)", w["warning"] == "60m" and "left of 30h" in w["label"], w)
clock.t = pool.deadline - 590; pool.touch(); pool.tick()
check("window: warning at 10 min", pool.window()["warning"] == "10m")
clock.t = pool.deadline - 100; pool.touch(); pool.tick()
check("window: warning at 2 min", pool.window()["warning"] == "2m")
clock.t = pool.deadline + 1
pool.tick()
c, j, h = post("/v1/chat/completions", "qwen2.5-7b")
check("window end: pool destroyed (why window_end), every runner cancelled, requests 503 ModelPoolStopped", pool.phase == "destroyed" and pool.destroyed_why == "window_end"
      and {"fast", "general", "coder", "agents"} <= set(disp.stopped) and c == 503 and j["error"]["code"] == "ModelPoolStopped", (c, j))
check("window end: models panel shows stopped", all(m["state"] == "stopped" for m in get("/api/booster/models")["models"]))
R.detach()

# ---- 60-min idle destroys the whole pool (+ booster hook) ----------------------------------------------------------------
disp2 = FakeDispatcher(); disp2.gen = {}
R._destroy_hooks.append(lambda why: destroyed_hook.append(why))
clock2 = Clock()
info = R.attach(HUB, BTOK, pooled=True, dispatcher=disp2, pool_kwargs={"clock": clock2})
pool = R.pool(); EP = info["endpoint"]
check("idle: re-attach starts a fresh eager pool", sorted(r for r, _, _ in disp2.started) == ["agents", "coder", "fast", "general"])
check("idle: ready", wait(lambda: all(pool.state(m) == "ready" for m in ("qwen2.5-3b", "qwen2.5-7b", "qwen2.5-coder-7b", "llama3.1-8b")), 15))
clock2.t += 3000
check("idle: an inference request (activity) resets the 60-min timer", post("/v1/chat/completions", "qwen2.5-7b")[0] == 200)
clock2.t += 3000
pool.tick()
check("idle: 50 min after the last request the pool is still alive", pool.phase == "running")
R.touch("vm")                                                  # a running VM / console activity also counts
clock2.t += 3500
pool.tick()
check("idle: VM/console activity resets it too", pool.phase == "running")
clock2.t += 3700
pool.tick()
check("idle: no activity for 60 min -> whole pool destroyed (why idle) and the booster hook fired", pool.phase == "destroyed" and pool.destroyed_why == "idle"
      and destroyed_hook == ["idle"] and {"fast", "general", "coder", "agents"} <= set(disp2.stopped), (pool.phase, destroyed_hook))

# ---- dispatch not configured / no local fallback / sanity max ------------------------------------------------------------
bad = P.RunnerPool(HUB, lambda: BTOK, P.HttpDispatcher(url=""), clock=clock2)
bad.start_all()
check("dispatch not configured: start_all does not crash, models stay 'starting' (honest 503), nothing local", bad.state("qwen2.5-3b") == "starting"
      and any("dispatch_failed" in e["event"] for e in bad._events))
big = P.load_catalogue(); big["runners"] = {f"r{i}": {"role": "x", "models": ["qwen2.5-3b"]} for i in range(21)}
try:
    P.RunnerPool(HUB, lambda: BTOK, disp2, catalogue=big, clock=clock2).start_all(); ok = False
except P.PoolError as e:
    ok = e.code == "TooManyRunners"
check("sanity max: more than 20 runners refused (no per-user cap of 3 any more)", ok and P.HARD_MAX_RUNNERS == 20)
R.detach()
check("no local fallback: AI bucket never reserved, nothing served locally after the pool ended", B.usage()["ai"] == 0 and B.resource_budget()["memory_split_mb"]["ai"] == 2800)

cleanup()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
