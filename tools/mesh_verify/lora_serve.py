"""(6) Real llama-server --lora with an adapter produced by trainer/lora_train.py (SmolLM2-135M-Instruct, 110 synthetic triage rows, 4 epochs).
Checks: server loads the adapter at start (--lora-scaled <file>:0), GET /lora-adapters shape (what core.llm_core.chat resolves the id from),
per-request ``lora:[{id,scale}]`` changes the output (scale 0 = base, 1 = tuned), exact-match on 12 fresh tickets with the adapter off vs on, and whether a
newly trained adapter can be picked up WITHOUT a restart (it cannot: the restart is required, which is the llm-chat restart hook gap).
Env: MV_LLAMA, MV_BASE_GGUF (Q8_0 of the same base), MV_ADAPTER (adapter.gguf)."""
import json, os, random, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.mesh_verify.common import post, get, rss_mb, save
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "trainer"))
import sample_data

PORT = 28095
base, adapter = os.environ["MV_BASE_GGUF"], os.environ["MV_ADAPTER"]


def start(extra):
    p = subprocess.Popen([f"{os.environ['MV_LLAMA']}/llama-server", "-m", base, "--host", "127.0.0.1", "--port", str(PORT), "-c", "2048", "-t", "2", "-ngl", "0", *extra],
                         stdout=open("/tmp/mv-lora-server.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            if get(f"http://127.0.0.1:{PORT}/health")["status"] == "ok":
                return p
        except Exception:
            time.sleep(1)
    raise TimeoutError("llama-server")


def ask(text, lora=None):
    b = {"messages": [{"role": "user", "content": text}], "max_tokens": 24, "temperature": 0}
    if lora is not None:
        b["lora"] = lora
    return post(f"http://127.0.0.1:{PORT}/v1/chat/completions", b)["choices"][0]["message"]["content"].strip()


def main():
    res = {"adapter_bytes": os.path.getsize(adapter), "base": os.path.basename(base)}
    rs = random.Random(991)
    tests = [(r["messages"][0]["content"], r["messages"][1]["content"]) if "messages" in r else (r["prompt"], r["completion"]) for r in sample_data.rows(400, 12345)]
    rs.shuffle(tests); tests = tests[:12]
    # 1) server started WITHOUT the adapter: the lora field must not exist/does nothing
    p = start([])
    res["no_adapter_server"] = {"lora_adapters": get(f"http://127.0.0.1:{PORT}/lora-adapters"), "exact": sum(ask(q) == a for q, a in tests)}
    p.terminate(); p.wait()
    # 2) server started WITH the adapter, unapplied
    p = start(["--lora-scaled", adapter + ":0"])
    la = get(f"http://127.0.0.1:{PORT}/lora-adapters")
    res["lora_adapters_endpoint"] = la
    aid = la[0]["id"]
    off = [ask(q, [{"id": aid, "scale": 0.0}]) for q, a in tests]
    on = [ask(q, [{"id": aid, "scale": 1.0}]) for q, a in tests]
    none = [ask(q) for q, a in tests]
    res["adapter_server"] = {"exact_scale0": sum(o == a for o, (q, a) in zip(off, tests)), "exact_scale1": sum(o == a for o, (q, a) in zip(on, tests)),
                             "exact_no_lora_field": sum(o == a for o, (q, a) in zip(none, tests)), "n": len(tests),
                             "samples": [{"q": q[:70], "want": a, "scale0": o0, "scale1": o1} for (q, a), o0, o1 in list(zip(tests, off, on))[:4]], "rss_mb": rss_mb(p.pid)}
    # 3) hot-adding a new adapter file is not possible without a restart: POST /lora-adapters only sets scales of the adapters loaded at start
    try:
        r = post(f"http://127.0.0.1:{PORT}/lora-adapters", [{"id": 99, "scale": 1.0}])
        res["post_unknown_id"] = str(r)[:200]
    except Exception as e:  # noqa: BLE001
        res["post_unknown_id"] = f"{type(e).__name__}: {e}"
    p.terminate(); p.wait()
    res["restart_hook_in_repo"] = {"mesh_compose_llm_chat_has_adapter_volume": "ai-adapters" in open(os.path.join(os.path.dirname(__file__), "..", "..", "codespace/.devcontainer/mesh/docker-compose.mesh.yml")).read()
                                   or "--lora" in open(os.path.join(os.path.dirname(__file__), "..", "..", "codespace/.devcontainer/mesh/docker-compose.mesh.yml")).read()}
    print(json.dumps(res, indent=1))
    save("lora_serve", res)


main()
