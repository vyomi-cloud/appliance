#!/usr/bin/env python3
"""Deterministic OpenAI-compatible stand-in for llama-server, used ONLY by the AI data-plane proof when no real model is
available on the host (no llama.cpp/Ollama model downloaded; disk guard forbids pulling one). It echoes the last user message
back, so the proof exercises the real Bedrock Converse/InvokeModel wire path -> core/llm_core HTTP backend -> model reply,
but the answer text is NOT model output. The runner records `model_backend: fake-echo` in proof.json.
    fake_llm_server.py <port>
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "conformance"))
from llm_fakes import FakeLLM

def echo(body):
    last = [m for m in body["messages"] if m.get("role") == "user"][-1]["content"]
    if isinstance(last, list):
        last = " ".join(p.get("text", "") for p in last)
    return {"content": f"ECHO: {last}"}

if __name__ == "__main__":
    import http.server
    port = int(sys.argv[1])
    _orig = http.server.ThreadingHTTPServer
    import llm_fakes
    llm_fakes.ThreadingHTTPServer = lambda addr, h: _orig(("127.0.0.1", port), h)
    f = FakeLLM(handler=echo, model="vyomi.qwen2.5-3b")
    print(f.url, flush=True)
    while True:
        time.sleep(3600)
