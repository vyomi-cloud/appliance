"""OPT-IN real tiny-model smoke for the booster AI pack (VYOMI_AI_SMOKE=1): real llama.cpp chat + embeddings containers,
real gateway, real llm_core, Bedrock Converse + Titan embed over the wire, ledger with exact tokens. Skips (exit 0) otherwise.

Downloads ~0.55 GB into VYOMI_AI_SMOKE_CACHE (default: a temp dir, removed afterwards). Chat model defaults to
Qwen2.5-0.5B-Instruct Q4_K_M (override VYOMI_AI_SMOKE_CHAT_HF); embeddings = bge-small. Checks free disk first.
Run: VYOMI_AI_SMOKE=1 PYTHONPATH=. python tests/conformance/test_booster_ai_smoke.py
"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import ThreadingHTTPServer

if os.environ.get("VYOMI_AI_SMOKE") != "1" or not shutil.which("docker"):
    print("[SKIP] set VYOMI_AI_SMOKE=1 with docker available to run the real tiny-model smoke"); sys.exit(0)
if shutil.disk_usage("/").free < 8e9:
    print("[SKIP] under 8 GB free disk"); sys.exit(0)

IMG = os.environ.get("VYOMI_LLM_IMAGE", "ghcr.io/ggml-org/llama.cpp:server")
CHAT_HF = os.environ.get("VYOMI_AI_SMOKE_CHAT_HF", "Qwen/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M")
EMB_HF = "CompendiumLabs/bge-small-en-v1.5-gguf:Q8_0"
cache = os.environ.get("VYOMI_AI_SMOKE_CACHE") or tempfile.mkdtemp(prefix="ai-smoke-")
os.environ["CLOUDLEARN_STATE_DIR"] = tempfile.mkdtemp(prefix="ai-smoke-state-")
PASS = FAIL = 0
names = []


def check(n, ok, d=""):
    global PASS, FAIL
    PASS, FAIL = PASS + bool(ok), FAIL + (not ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {n}{' - ' + str(d)[:300] if d and not ok else ''}")


def run(name, hf, port, extra):
    names.append(name)
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    r = subprocess.run(["docker", "run", "-d", "--name", name, "-v", f"{cache}:/root/.cache", "-p", f"127.0.0.1:{port}:8080", IMG,
                        "-hf", hf, "--host", "0.0.0.0", "--port", "8080", "-np", "1", "-t", "2", *extra], capture_output=True, text=True)
    return r.returncode == 0


def wait(url, secs=900):
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            urllib.request.urlopen(url + "/health", timeout=3).read(); return True
        except Exception:
            time.sleep(4)
    return False


def cleanup():
    for n in names:
        subprocess.run(["docker", "rm", "-f", n], capture_output=True)
    if not os.environ.get("VYOMI_AI_SMOKE_CACHE"):
        shutil.rmtree(cache, ignore_errors=True)


try:
    ok = run("vyomi-ai-smoke-chat", CHAT_HF, 18181, ["-c", "2048", "--jinja"]) and run("vyomi-ai-smoke-embed", EMB_HF, 18182, ["--embeddings", "-c", "512"])
    check("containers started", ok)
    chat_url, emb_url = "http://127.0.0.1:18181", "http://127.0.0.1:18182"
    up = ok and wait(chat_url) and wait(emb_url)
    check("both llama-server instances healthy (model pulled + loaded)", up)
    if up:
        from core import booster_llm_gateway as GW, booster_ai as AI, llm_core
        gw = ThreadingHTTPServer(("127.0.0.1", 0), type("G", (GW.Handler,), {"chat_url": chat_url, "embed_url": emb_url}))
        threading.Thread(target=gw.serve_forever, daemon=True).start()
        os.environ["VYOMI_LLM_ENDPOINT"] = f"http://127.0.0.1:{gw.server_address[1]}"
        AI.install(); AI.LEDGER.reset("smoke")
        AI.CLOUD.set("aws"); AI.OP.set("converse")
        r = llm_core.chat([{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=16, temperature=0)
        check("real model answers through gateway+seam with exact (non-estimated) token counts", r["text"].strip() and r["input_tokens"] > 5 and r["output_tokens"] >= 1 and r["backend"] == "llama.cpp", r)
        e = llm_core.embed(["hello world", "goodbye moon"])
        check("real embeddings model (not hash fallback): 384-d", e["backend"] == "llama.cpp" and e["dimensions"] == 384, {k: e[k] for k in ("backend", "dimensions")})
        a, b = llm_core.embed(["the cat sat on the mat"])["vectors"][0], llm_core.embed(["a kitten sits on a rug"])["vectors"][0]
        c_ = llm_core.embed(["quarterly tax filing deadlines"])["vectors"][0]
        check("embeddings are semantic (similar > unrelated)", llm_core.cosine(a, b) > llm_core.cosine(a, c_), (llm_core.cosine(a, b), llm_core.cosine(a, c_)))
        s = AI.LEDGER.summary()
        check("ledger recorded the real calls", s["totals"]["requests"] >= 4 and s["totals"]["input_tokens"] > 0 and s["by_cloud"]["aws"]["requests"] >= 4, s["totals"])
        print("  sample:", repr(r["text"][:80]), "| latency_ms:", s["recent"][0]["latency_ms"])
finally:
    cleanup()
print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
