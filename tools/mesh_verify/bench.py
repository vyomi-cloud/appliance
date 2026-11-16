"""(1) Real tokens/s + RAM: chat alone, chat + vision (SmolVLM-500M), chat + reasoning (R1-1.5B), and does core.llm_runtime.plan_role_start swap right.

The real core.llm_runtime.role_start() is driven with an injected ``run`` (its documented test seam) that maps the docker commands onto NATIVE
llama-server processes (this host has no Docker image budget). So plan_role_start/role_start/role_status logic is the real code; only the
container is replaced by a process. Env: MV_LLAMA=<dir with llama-server> MV_MODELS=<dir with the gguf files> MV_CHAT_PID=<pid of the running chat server>.
"""
import base64, json, os, signal, struct, subprocess, sys, time, zlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.mesh_verify.common import post, get, rss_mb, save, CHAT
from core import llm_runtime as rt

LLAMA, MODELS = os.environ["MV_LLAMA"], os.environ["MV_MODELS"]
PORT_OFF = int(os.environ.get("MV_PORT_OFFSET", "10000"))    # host ports 18081/18082 (+10000) so a foreign server on 18080 is never touched
THREADS = os.environ.get("MV_THREADS", "4")


def png(w=96, h=96):
    """A white 96x96 PNG with a solid red square: the vision prompt asks what colour the square is."""
    rows = b"".join(b"\x00" + b"".join((b"\xff\x00\x00" if 24 <= x < 72 and 24 <= y < 72 else b"\xff\xff\xff") for x in range(w)) for y in range(h))
    def ck(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ck(b"IDAT", zlib.compress(rows)) + ck(b"IEND", b"")


class Fake:
    """docker CLI -> native llama-server processes. procs: name -> {pid, port, argv, state}."""
    def __init__(self, chat_pid, chat_port):
        self.p = {rt.NAME: {"pid": chat_pid, "port": chat_port, "argv": None, "state": "running"}}
        self.log = []

    def _alive(self, pid):
        try: os.kill(pid, 0); return True
        except OSError: return False

    def __call__(self, args):
        self.log.append(args)
        if args[0] == "ps":
            name = args[3].split("name=^")[1].rstrip("$")
            e = self.p.get(name)
            if e and e["state"] == "running" and not self._alive(e["pid"]):
                e["state"] = "exited"
            return 0, (e["state"] if e else ""), ""
        if args[0] == "stop":
            e = self.p.get(args[1])
            if e and e["state"] == "running":
                os.kill(e["pid"], signal.SIGTERM)
                for _ in range(50):
                    if not self._alive(e["pid"]): break
                    time.sleep(0.1)
                e["state"] = "exited"
            return 0, "", ""
        if args[0] == "start":
            e = self.p[args[1]]
            if e["argv"] is None:
                return 1, "", "cannot restart the foreign chat server"
            e["pid"] = subprocess.Popen(e["argv"], stdout=open(f"/tmp/mv-{args[1]}.log", "a"), stderr=subprocess.STDOUT).pid
            e["state"] = "running"
            return 0, args[1], ""
        if args[0] == "run":
            name = args[args.index("--name") + 1]
            hf = args[args.index("-hf") + 1]
            hostport = int(args[args.index("-p") + 1].split(":")[1]) + PORT_OFF
            if "SmolVLM" in hf:
                m = ["-m", f"{MODELS}/SmolVLM-500M-Instruct-Q8_0.gguf", "--mmproj", f"{MODELS}/mmproj-SmolVLM-500M-Instruct-Q8_0.gguf"]
            elif "R1-Distill" in hf:
                m = ["-m", f"{MODELS}/DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf"]
            else:
                return 1, "", f"no local file mapped for {hf}"
            extra = args[args.index("-c"):]          # -c 4096 --jinja [--reasoning-format deepseek]
            argv = [f"{LLAMA}/llama-server", *m, "--host", "127.0.0.1", "--port", str(hostport), "-t", THREADS, "-ngl", "0", "--no-mmproj-offload", *extra]
            proc = subprocess.Popen(argv, stdout=open(f"/tmp/mv-{name}.log", "w"), stderr=subprocess.STDOUT)
            self.p[name] = {"pid": proc.pid, "port": hostport, "argv": argv, "state": "running"}
            return 0, name, ""
        return 1, "", f"unsupported {args}"

    def wait_ready(self, name, timeout=180):
        e = self.p[name]
        t = time.time()
        while time.time() - t < timeout:
            try:
                if get(f"http://127.0.0.1:{e['port']}/health")["status"] == "ok": return round(time.time() - t, 1)
            except Exception: pass
            time.sleep(0.5)
        raise TimeoutError(name)


def gen(port, prompt, max_tokens=160, extra=None, content=None):
    body = {"messages": [{"role": "user", "content": content or prompt}], "max_tokens": max_tokens, "temperature": 0.2}
    body.update(extra or {})
    t = time.time()
    r = post(f"http://127.0.0.1:{port}/v1/chat/completions", body)
    tm = r.get("timings", {})
    return {"wall_s": round(time.time() - t, 1), "completion_tokens": r["usage"]["completion_tokens"], "prompt_tokens": r["usage"]["prompt_tokens"],
            "decode_tok_s": round(tm.get("predicted_per_second", 0), 2), "prefill_tok_s": round(tm.get("prompt_per_second", 0), 2),
            "text": r["choices"][0]["message"].get("content", "")[:160], "reasoning": (r["choices"][0]["message"].get("reasoning_content") or "")[:120]}


def main():
    chat_port = int(CHAT.rsplit(":", 1)[1]); chat_pid = int(os.environ["MV_CHAT_PID"])
    fk = Fake(chat_pid, chat_port)
    res = {"chat_alone": {}, "plan": {}}
    long_prompt = "Summarise in one sentence: " + ("The facilities team reviewed HVAC maintenance logs, chiller inspection results and work-order backlog for building 7. " * 30)
    gen(chat_port, "Say hi.", 8)    # warm
    res["chat_alone"] = {"short_gen": [gen(chat_port, "Explain what a chiller does in a data centre, in about 120 words.", 160) for _ in range(3)],
                         "long_prefill": gen(chat_port, long_prompt, 40), "rss_mb": rss_mb(chat_pid)}
    # --- plan decisions (pure function) on the 8 GB-Codespace budget (code default) and on the 16 GB Mesh default
    for label, budget in (("budget_2800_default_8GB_codespace", rt.AI_BUDGET_MB), ("budget_9000_16GB_mesh_assumed", 9000)):
        res["plan"][label] = {"vision_with_chat": rt.plan_role_start("vision", ["chat"], budget), "reasoning_with_chat": rt.plan_role_start("reasoning", ["chat"], budget),
                              "reasoning_with_chat_vision": rt.plan_role_start("reasoning", ["chat", "vision"], budget)}
    # --- REAL role_start with the 16 GB budget (monkeypatched constant; the 2800 default is exercised in the swap step below)
    rt.AI_BUDGET_MB = 9000
    orig = rt.plan_role_start
    rt.plan_role_start = lambda role, running, budget_mb=9000: orig(role, running, budget_mb)
    free = lambda path="/": 100.0
    out = {}
    st = rt.role_start("vision", run=fk, disk=free)
    out["vision_start"] = {"plan": st["plan"], "ready_s": fk.wait_ready("vyomi-llm-vision")}
    vp = fk.p["vyomi-llm-vision"]
    img = "data:image/png;base64," + base64.b64encode(png()).decode()
    vcontent = [{"type": "text", "text": "What colour is the square in this image? Answer in one word."}, {"type": "image_url", "image_url": {"url": img}}]
    out["vision_gen"] = gen(vp["port"], None, 20, content=vcontent)
    out["chat_during_vision"] = gen(chat_port, "Say hi in five words.", 24)
    out["rss_mb_chat_plus_vision"] = {"chat": rss_mb(chat_pid), "vision": rss_mb(vp["pid"])}
    st = rt.role_start("reasoning", run=fk, disk=free)      # budget 9000: vision (900) + chat (2500) + reasoning (1500) fits -> nothing stops
    out["reasoning_start_budget9000"] = {"plan": st["plan"], "ready_s": fk.wait_ready("vyomi-llm-reasoning")}
    rp = fk.p["vyomi-llm-reasoning"]
    out["reasoning_gen"] = gen(rp["port"], "A shop sells pens at 3 for 2 dollars. How many dollars for 12 pens? Think briefly, then give the number.", 400)
    out["rss_mb_all_three"] = {"chat": rss_mb(chat_pid), "vision": rss_mb(vp["pid"]), "reasoning": rss_mb(rp["pid"])}
    res["three_up_16GB_budget"] = out
    # --- swap on the code-default 2800 MB budget: all roles stopped, chat running; starting vision must STOP chat (2500+900 > 2800)
    rt.plan_role_start = orig
    rt.AI_BUDGET_MB = 2800
    for r_ in ("vyomi-llm-reasoning", "vyomi-llm-vision"):
        fk(["stop", r_])
    sw = {}
    st = rt.role_start("vision", run=fk, disk=free)          # installed (exited) -> docker start path
    sw["start_vision_on_2800_with_chat"] = {"plan": st["plan"], "ready_s": fk.wait_ready("vyomi-llm-vision")}
    sw["chat_state_after"] = fk(["ps", "-a", "--filter", "name=^vyomi-llm$", "--format", "{{.State}}"])[1]
    sw["vision_state_after"] = fk(["ps", "-a", "--filter", "name=^vyomi-llm-vision$", "--format", "{{.State}}"])[1]
    sw["vision_gen_after_swap"] = gen(fk.p["vyomi-llm-vision"]["port"], None, 20, content=vcontent)
    res["swap_2800_default_budget"] = sw
    for n, e in fk.p.items():
        if n != rt.NAME and e["state"] == "running":
            os.kill(e["pid"], signal.SIGTERM)
    res["docker_commands_issued"] = [a[:2] for a in fk.log if a[0] in ("run", "stop", "start")]
    print(json.dumps(save("bench", res), indent=1))


main()
