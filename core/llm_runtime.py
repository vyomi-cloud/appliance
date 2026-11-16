"""Offline-substrate lifecycle of the local-LLM container the shared seam (core/llm_core) talks to. NOT loaded on Nano.

A single llama.cpp ``llama-server`` container (name ``vyomi-llm``) serving an OpenAI-compatible API on 8080 with a SMALL GGUF
model (default HuggingFaceTB SmolLM2-360M-Instruct Q8_0, ~380 MB, downloaded on first start by llama-server's ``-hf`` into the named volume
``vyomi-llm-models``; override with VYOMI_LLM_IMAGE / VYOMI_LLM_HF_MODEL). The image is a ~100-200 MB CPU build. Nothing is pulled
or started until ``start()`` is called explicitly (CLI/console action), and ``start`` refuses when free disk is below the guard.

    status() -> {"installed", "running", "image", "model", "endpoint", "free_disk_gb"}
    start() / stop() / remove()  (docker is injected as ``run`` so tests stub it)
"""
from __future__ import annotations

import os
import shutil
import subprocess

NAME = "vyomi-llm"
VOLUME = "vyomi-llm-models"
IMAGE = os.environ.get("VYOMI_LLM_IMAGE", "ghcr.io/ggml-org/llama.cpp:server")
HF_MODEL = os.environ.get("VYOMI_LLM_HF_MODEL", "HuggingFaceTB/SmolLM2-360M-Instruct-GGUF:Q8_0")   # official repo; the old ggml-org mirror was removed (HF 401)
MIN_FREE_GB = float(os.environ.get("VYOMI_LLM_MIN_FREE_GB", "20"))


class RuntimeError_(Exception):
    pass


def _run(args, run=None):
    if run:
        return run(args)
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def lora_args(adapter_dir: str | None = None, mount: str = "/adapters") -> list[str]:
    """llama-server flags that load every ``*.gguf`` LoRA adapter in ``adapter_dir`` (default core.llm_core.lora_dir()) at start, at scale 0
    (requests opt in per call with ``lora: [{id, scale}]``). The directory must be mounted at ``mount``. Empty when there are none."""
    d = adapter_dir or os.environ.get("VYOMI_LLM_ADAPTER_DIR") or os.path.join(os.environ.get("CLOUDLEARN_DATA_DIR", "/data"), "llm-adapters")
    files = sorted(f for f in (os.listdir(d) if os.path.isdir(d) else []) if f.endswith(".gguf"))
    if not files:
        return []
    out = []
    for f in files:       # ``--lora-scaled <file>:0``: loaded at scale 0, so a request WITHOUT ``lora`` is the base model (measured: ``--lora-init-without-apply`` applies the adapter at scale 1.0 on b12441)
        out += ["--lora-scaled", f"{mount}/{f}:0"]
    return out


def free_disk_gb(path="/") -> float:
    return round(shutil.disk_usage(path).free / 1e9, 1)


def status(run=None, disk=free_disk_gb) -> dict:
    rc, out, _ = _run(["ps", "-a", "--filter", f"name=^{NAME}$", "--format", "{{.State}}"], run)
    running = rc == 0 and out.strip() == "running"
    return {"installed": rc == 0 and bool(out.strip()), "running": running, "image": IMAGE, "model": HF_MODEL,
            "endpoint": f"http://{NAME}:8080", "free_disk_gb": disk()}


def start(run=None, disk=free_disk_gb, network: str | None = None) -> dict:
    st = status(run, disk)
    if st["running"]:
        return st
    if st["free_disk_gb"] < MIN_FREE_GB:
        raise RuntimeError_(f"Refusing to start the local LLM: only {st['free_disk_gb']} GB free disk (guard {MIN_FREE_GB} GB).")
    if st["installed"]:
        rc, _, err = _run(["start", NAME], run)
    else:
        args = ["run", "-d", "--name", NAME, "--restart", "unless-stopped", "-v", f"{VOLUME}:/root/.cache", "-p", "127.0.0.1:18080:8080"]
        if network:
            args += ["--network", network]
        la = lora_args()
        if la:      # trained chat-LoRA adapters (core/training_core): mount the adapter dir read-only and load them unapplied
            d = os.environ.get("VYOMI_LLM_ADAPTER_DIR") or os.path.join(os.environ.get("CLOUDLEARN_DATA_DIR", "/data"), "llm-adapters")
            args += ["-v", f"{d}:/adapters:ro"]
        args += [IMAGE, "-hf", HF_MODEL, "--host", "0.0.0.0", "--port", "8080", "-c", "4096", "--embeddings", "--jinja", *la]
        rc, _, err = _run(args, run)
    if rc != 0:
        raise RuntimeError_(f"docker could not start {NAME}: {err}")
    return status(run, disk)


def stop(run=None) -> dict:
    _run(["stop", NAME], run)
    return status(run)


def remove(run=None, purge_models=False) -> None:
    _run(["rm", "-f", NAME], run)
    if purge_models:
        _run(["volume", "rm", VOLUME], run)


# ───────────────────────── role models (vision / reasoning), Mesh only ─────────────────────────
# One extra llama-server container per role, each with its own small GGUF. An 8 GB Codespace has only ~2.8 GB for the AI bucket, so roles are
# started ON DEMAND and ``plan_role_start`` stops whatever would push the running set over the budget (the default chat model is stopped
# last-resort, never silently: the plan is returned to the caller). File sizes are measured; ``est_mb`` is a planning ESTIMATE (file size + KV/overhead),
# not a measurement - measure on the real Codespace (see docs/architecture/v4.0/branches/ai-limmodels.md).
ROLES = {
    "vision": {"name": "vyomi-llm-vision", "hf": os.environ.get("VYOMI_LLM_VISION_HF", "ggml-org/SmolVLM-500M-Instruct-GGUF:Q8_0"), "port": 18081,
               "files_mb": 545, "est_mb": 900, "args": ["--jinja"], "env": "VYOMI_LLM_VISION_ENDPOINT", "licence": "Apache-2.0"},
    "reasoning": {"name": "vyomi-llm-reasoning", "hf": os.environ.get("VYOMI_LLM_REASONING_HF", "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF:Q4_K_M"), "port": 18082,
                  "files_mb": 1117, "est_mb": 1800, "args": ["--jinja", "--reasoning-format", "deepseek"], "env": "VYOMI_LLM_REASONING_ENDPOINT", "licence": "MIT"},
}
CHAT_EST_MB = 2500          # Qwen2.5-3B Q4 + KV (estimate)


def total_ram_mb() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1048576)
    except (ValueError, OSError, AttributeError):
        return 8192


def default_budget_mb() -> int:
    """AI-bucket RAM budget: VYOMI_LLM_AI_BUDGET_MB, else 35 % of physical RAM with a 2800 MB floor (2800 MB was exactly 35 % of the old 8 GB Codespace; the
    4 vCPU / 16 GB Mesh default gets 5600 MB, so the chat model is no longer stopped to start a 0.5-1.7 GB role model: measured RSS in ai-meshverify.md)."""
    return int(os.environ.get("VYOMI_LLM_AI_BUDGET_MB") or max(2800, int(total_ram_mb() * 0.35)))


AI_BUDGET_MB = default_budget_mb()


def plan_role_start(role: str, running: list[str], budget_mb: int | None = None) -> dict:
    """Which running AI containers must stop for ``role`` to fit: other roles first, then the default chat model. -> {"stop": [...], "fits": bool, "total_mb": n}."""
    budget_mb = AI_BUDGET_MB if budget_mb is None else budget_mb
    est = {"chat": CHAT_EST_MB, **{r: v["est_mb"] for r, v in ROLES.items()}}
    keep = [r for r in running if r != role]
    stop = []
    while keep and sum(est[r] for r in keep) + est[role] > budget_mb:
        victim = next((r for r in keep if r != "chat"), keep[0])      # other roles go before the chat model
        keep.remove(victim)
        stop.append(victim)
    total = sum(est[r] for r in keep) + est[role]
    return {"stop": stop, "fits": total <= budget_mb, "total_mb": total}


def role_status(role: str, run=None) -> dict:
    r = ROLES[role]
    rc, out, _ = _run(["ps", "-a", "--filter", f"name=^{r['name']}$", "--format", "{{.State}}"], run)
    return {"role": role, "installed": rc == 0 and bool(out.strip()), "running": rc == 0 and out.strip() == "running", "model": r["hf"],
            "endpoint": f"http://{r['name']}:8080", "licence": r["licence"], "env": r["env"]}


def role_start(role: str, run=None, disk=free_disk_gb, network: str | None = None) -> dict:
    """Start the role's llama-server (``-hf`` pulls the GGUF, plus the mmproj for vision, into the shared models volume on first start)."""
    r = ROLES[role]
    st = role_status(role, run)
    if st["running"]:
        return st
    if disk() < MIN_FREE_GB:
        raise RuntimeError_(f"Refusing to start the {role} model: only {disk()} GB free disk (guard {MIN_FREE_GB} GB).")
    running = [x for x in ROLES if role_status(x, run)["running"]] + (["chat"] if status(run, disk)["running"] else [])
    plan = plan_role_start(role, running)
    for victim in plan["stop"]:
        _run(["stop", NAME if victim == "chat" else ROLES[victim]["name"]], run)
    if st["installed"]:
        rc, _, err = _run(["start", r["name"]], run)
    else:
        args = ["run", "-d", "--name", r["name"], "--restart", "unless-stopped", "-v", f"{VOLUME}:/root/.cache", "-p", f"127.0.0.1:{r['port']}:8080"]
        if network:
            args += ["--network", network]
        args += [IMAGE, "-hf", r["hf"], "--host", "0.0.0.0", "--port", "8080", "-c", "4096", *r["args"]]
        rc, _, err = _run(args, run)
    if rc != 0:
        raise RuntimeError_(f"docker could not start {r['name']}: {err}")
    return dict(role_status(role, run), plan=plan)


def role_stop(role: str, run=None) -> dict:
    _run(["stop", ROLES[role]["name"]], run)
    return role_status(role, run)
