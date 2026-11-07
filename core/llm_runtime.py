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
        args += [IMAGE, "-hf", HF_MODEL, "--host", "0.0.0.0", "--port", "8080", "-c", "4096", "--embeddings", "--jinja"]
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
