"""llama.cpp RPC over the LLM mesh (docs/architecture/v4.0/BOOSTER-LLM-MESH.md section 7). OPTIONAL: needs Docker, the image
vyomi-mesh-llama:test (docker build -f docker/booster-mesh-test/Dockerfile.rpc ...) and a small gguf (env MESH_RPC_MODEL=/path/x.gguf).
Skips cleanly otherwise.

relay + 3 'runner' containers on separate bridges (outbound-only). r1 and r2 run `rpc-server` bound to their WG address ONLY;
r3 runs `llama-server --rpc 100.96.1.1:50052,100.96.1.2:50052 -ngl 99`. Confirms the layers split across the two RPC devices, tokens
return, and reports tokens/s vs the same model on a single node (r3 alone, same thread count).

Run: MESH_RPC_MODEL=/path/model.gguf PYTHONPATH=. python3 tests/conformance/test_booster_mesh_rpc.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
from core import booster_mesh as M  # noqa: E402

KEY = "mesh-test-key-0123456789abcdef"
IMG = "vyomi-mesh-llama:test"
MODEL = os.environ.get("MESH_RPC_MODEL", "")
PASS = FAIL = 0
RES = {}


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:400] if detail and not ok else ''}", flush=True)


def sh(*a, timeout=120):
    return subprocess.run(list(a), capture_output=True, text=True, timeout=timeout)


def dx(nm, cmd, timeout=120):
    return sh("docker", "exec", nm, "bash", "-c", cmd, timeout=timeout)


if not shutil.which("docker") or sh("docker", "info", timeout=20).returncode or sh("docker", "image", "inspect", IMG).returncode or not (MODEL and os.path.exists(MODEL)):
    print("[SKIP] needs Docker + image vyomi-mesh-llama:test + MESH_RPC_MODEL=<small.gguf>")
    sys.exit(0)

relay = "vyomi-mesh-relay"
names = {"r1": "vyomi-mesh-r1", "r2": "vyomi-mesh-r2", "r3": "vyomi-mesh-r3"}
nets = [f"vyomi-mesh-net{i}" for i in range(3)]


def cleanup():
    sh("docker", "rm", "-f", relay, *names.values())
    for n in nets:
        sh("docker", "network", "rm", n)


cleanup()
try:
    end = int(time.time()) + 3600
    cfgs = M.mint_mesh_session("sess-rpc", [{"id": k, "role": "runner"} for k in names], account="a", relay_url=f"ws://{relay}:8787", session_end=end, key=KEY)
    for n in nets:
        sh("docker", "network", "create", n)
    mounts = ["-v", f"{ROOT}/wasm/relay:/opt/relay:ro", "-v", f"{ROOT}/docker/booster-runner-llm:/opt/rl:ro", "-v", f"{ROOT}/docker/booster-mesh-test:/opt/test:ro"]
    sh("docker", "run", "-d", "--name", relay, "--network", nets[0], "--cap-add", "NET_ADMIN", "--sysctl", "net.ipv4.ip_forward=1", "--cpus", "1", "--memory", "512m",
       "-e", f"VYOMI_BOOSTER_SESSION_KEY={KEY}", "-e", "WS_PKG=/opt/runner/node_modules/ws", *mounts, "--entrypoint", "node", IMG, "/opt/test/mesh-relay.mjs")
    for n in nets[1:]:
        sh("docker", "network", "connect", n, relay)
    for (k, nm), net in zip(names.items(), nets):
        extra = ["-v", f"{os.path.abspath(MODEL)}:/models/m.gguf:ro"] if k == "r3" else []
        sh("docker", "run", "-d", "--name", nm, "--hostname", k, "--network", net, "--cap-add", "NET_ADMIN", "--cpus", "2", "--memory", "2g", *mounts, *extra,
           "-e", "WS_PKG=/opt/runner/node_modules/ws", "-e", "MESH_JS=/opt/relay/booster-mesh.mjs", "--entrypoint", "sleep", IMG, "infinity")
    time.sleep(2)
    for k, nm in names.items():
        c = cfgs[k]
        r = dx(nm, f"VYOMI_RELAY_URL={c['relay_url']} VYOMI_MESH_TOKEN='{c['env']['VYOMI_MESH_TOKEN']}' bash /opt/rl/mesh-up.sh up", timeout=90)
        check(f"{k} joined the mesh ({c['address']})", r.returncode == 0, r.stdout + r.stderr)
    a1, a2 = cfgs["r1"]["address"], cfgs["r2"]["address"]
    for k, a in (("r1", a1), ("r2", a2)):
        dx(names[k], f"(nohup /app/rpc-server -H {a} -p 50052 -t 2 > /tmp/rpc.log 2>&1 &) ; sleep 2")
        ls = dx(names[k], "ss -H -ltn | awk '{print $4}'").stdout.split()
        check(f"{k}: rpc-server listens on the WG address only", f"{a}:50052" in ls and not any(x.startswith(("0.0.0.0", "*", "[::]")) for x in ls), ls)
    driver = names["r3"]
    # single node baseline: same model, same threads, no RPC
    body = json.dumps({"prompt": "Write a short poem about the sea.", "n_predict": 48, "temperature": 0, "cache_prompt": False})

    def run_server(extra, port):
        dx(driver, f"pkill llama-server; sleep 1; (nohup /app/llama-server -m /models/m.gguf --host 127.0.0.1 --port {port} -c 1024 -t 2 {extra} > /tmp/ls{port}.log 2>&1 &)")
        t0 = time.time()
        while time.time() - t0 < 600:
            if dx(driver, f"curl -s -m 3 http://127.0.0.1:{port}/health").stdout.find('"ok"') >= 0:
                return time.time() - t0
            time.sleep(3)
        return None

    def complete(port):
        o = dx(driver, f"curl -s -m 300 http://127.0.0.1:{port}/completion -d '{body}'", timeout=320).stdout
        j = json.loads(o)
        return j["timings"], j.get("content", "")

    ld = run_server("", 8090)
    check("single node: model loads and serves", ld is not None)
    RES["single_load_s"] = round(ld or 0, 1)
    tm, txt = complete(8090)
    RES["single_tokens_per_s"] = round(tm["predicted_per_second"], 2)
    RES["single_prompt_tokens_per_s"] = round(tm["prompt_per_second"], 2)
    check("single node: tokens returned", len(txt) > 10, txt)

    ld = run_server(f"--rpc {a1}:50052,{a2}:50052 -ngl 99", 8091)
    check("RPC: llama-server --rpc over the mesh loads the model", ld is not None, dx(driver, "tail -5 /tmp/ls8091.log").stdout)
    RES["rpc_load_s"] = round(ld or 0, 1)
    log = dx(driver, "cat /tmp/ls8091.log").stdout
    bufs = dict(re.findall(r"(RPC\d*)[^\n]*model buffer size\s*=\s*([\d.]+) MiB", log))
    RES["rpc_buffers_MiB"] = bufs
    tm, txt = complete(8091)
    check("RPC: tokens return", len(txt) > 10, txt)
    RES["rpc2_tokens_per_s"] = round(tm["predicted_per_second"], 2)
    RES["rpc2_prompt_tokens_per_s"] = round(tm["prompt_per_second"], 2)
    # which peer carried the traffic
    rx = [int(dx(names[k], "wg show wgvyomi transfer | awk '{print $2}'").stdout.strip() or 0) for k in ("r1", "r2")]
    RES["wg_rx_bytes_r1_r2"] = rx
    # the split is proven by the bytes each rpc-server received over the mesh (the stock log does not print per-device buffers):
    # together ~ the model size, each a substantial share
    msize = os.path.getsize(MODEL)
    check("RPC: the layers split across both rpc-servers (each received a share; together ~ the model size)", all(x > 0.25 * msize for x in rx) and sum(rx) > 0.8 * msize, (rx, msize))
finally:
    if os.environ.get("MESH_KEEP") != "1":
        cleanup()
print("RESULTS " + json.dumps(RES))
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
