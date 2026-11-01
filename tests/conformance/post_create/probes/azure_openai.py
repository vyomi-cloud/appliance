#!/usr/bin/env python3
"""Post-create probe (offline): an Azure OpenAI account must be creatable with common model deployments and serve a
(SIMULATED, labelled) inference endpoint reachable from this machine with the account key.
  python3 azure_openai.py http://localhost:9000"""
import json, os, sys, urllib.error, urllib.request

BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
SUB, RG, ACC = "00000000-0000-0000-0000-cloudlearn01", "probe-ai-rg", "probeaoai"
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1


def call(method, url, body=None, headers=None):
    req = urllib.request.Request(url if url.startswith("http") else BASE + url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = r.read()
            return r.status, (json.loads(d) if d else {})
    except urllib.error.HTTPError as e:
        d = e.read()
        return e.code, (json.loads(d) if d else {})


call("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}?api-version=2021-04-01", {"location": "eastus"})
A = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.CognitiveServices/accounts/{ACC}"
try:
    s, acc = call("PUT", A + "?api-version=2024-10-01", {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": ACC}})
    check(s in (200, 201), "create OpenAI account", acc)
    s, d = call("PUT", A + "/deployments/gpt4o?api-version=2024-10-01", {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}}})
    check(s in (200, 201), "gpt-4o deployment accepted (was DeploymentModelNotSupported)", d)
    call("PUT", A + "/deployments/emb?api-version=2024-10-01", {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "text-embedding-3-small", "version": "1"}}})
    s, keys = call("POST", A + "/listKeys?api-version=2024-10-01", {})
    s, acc = call("GET", A + "?api-version=2024-10-01")
    ep = acc["properties"]["endpoint"].rstrip("/")
    check(ep.startswith("http://") or "localhost" in ep, "account endpoint is served by the simulator (reachable from this machine)", ep)
    h = {"api-key": keys["key1"]}
    s, r = call("POST", f"{ep}/openai/deployments/gpt4o/chat/completions?api-version=2024-10-21", {"messages": [{"role": "user", "content": "ping"}]}, h)
    check(s == 200 and "SIMULATED" in r["choices"][0]["message"]["content"] and r["usage"]["total_tokens"] > 0,
          "chat/completions returns Azure OpenAI shape, labelled simulated", (s, r))
    s, r = call("POST", f"{ep}/openai/deployments/emb/embeddings?api-version=2024-10-21", {"input": "hi"}, h)
    check(s == 200 and len(r["data"][0]["embedding"]) == 1536, "embeddings return a 1536-d vector", (s, str(r)[:200]))
    s, r = call("POST", f"{ep}/openai/deployments/gpt4o/chat/completions?api-version=2024-10-21", {"messages": [{"role": "user", "content": "x"}]}, {"api-key": "wrong"})
    check(s == 401, "a wrong api-key is rejected (401)", s)
finally:
    call("DELETE", A + "?api-version=2024-10-01")
    call("DELETE", f"/subscriptions/{SUB}/resourcegroups/{RG}?api-version=2021-04-01")
sys.exit(1 if fails else 0)
