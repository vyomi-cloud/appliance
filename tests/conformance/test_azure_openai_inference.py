"""Simulated Azure OpenAI inference through the ARM entrypoint (offline + Nano share it)
(run: python3 tests/conformance/test_azure_openai_inference.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail)[:300] if detail and not ok else ''}")


arm = AzureArm({})
SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
arm.handle("PUT", SUB + "/resourcegroups/rg1", {"api-version": "2021-04-01"}, {"location": "eastus"})
A = SUB + "/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/aoai1"
V = {"api-version": "2024-10-01"}
r = arm.handle("PUT", A, V, {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "aoai1"}})
check("account created", r["status"] in (200, 201), r)
for model, ver in (("gpt-4o", "2024-11-20"), ("gpt-4o", "latest"), ("gpt-4.1", "2025-04-14"), ("text-embedding-3-small", "1")):
    r = arm.handle("PUT", A + "/deployments/d-" + model.replace(".", "") + ver.replace("-", ""), V,
                   {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": model, "version": ver}}})
    check(f"deployment {model}@{ver} creatable", r["status"] in (200, 201), r["body"])
r = arm.handle("PUT", A + "/deployments/bad", V, {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "no-such-model", "version": "1"}}})
check("unknown model still rejected", r["status"] == 400 and r["body"]["error"]["code"] == "DeploymentModelNotSupported", r["body"])
arm.handle("PUT", A + "/deployments/chat", V, {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}}})
arm.handle("PUT", A + "/deployments/emb", V, {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "text-embedding-3-small", "version": "1"}}})
P = {"api-version": "2024-10-21"}
req = {"messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello azure"}]}
r1 = arm.handle("POST", A + "/openai/deployments/chat/chat/completions", P, req)
b = r1["body"]
check("chat/completions shape: id, choices[0].message.content, usage", r1["status"] == 200 and b["id"].startswith("chatcmpl-")
      and b["choices"][0]["message"]["role"] == "assistant" and b["usage"]["total_tokens"] == b["usage"]["prompt_tokens"] + b["usage"]["completion_tokens"], b)
check("output is clearly labelled simulated and echoes the prompt", "SIMULATED" in b["choices"][0]["message"]["content"] and "hello azure" in b["choices"][0]["message"]["content"])
check("deterministic", arm.handle("POST", A + "/openai/deployments/chat/chat/completions", P, req)["body"]["choices"] == b["choices"])
e = arm.handle("POST", A + "/openai/deployments/emb/embeddings", P, {"input": ["a", "b"]})["body"]
check("embeddings: 2 vectors x 1536, unit norm, deterministic", len(e["data"]) == 2 and len(e["data"][0]["embedding"]) == 1536
      and abs(sum(x * x for x in e["data"][0]["embedding"]) - 1) < 1e-3 and e["data"][0]["embedding"] != e["data"][1]["embedding"])
check("embeddings op on chat model -> 400 OperationNotSupported", arm.handle("POST", A + "/openai/deployments/chat/embeddings", P, {"input": "x"})["status"] == 400)
check("missing deployment -> 404 DeploymentNotFound", arm.handle("POST", A + "/openai/deployments/nope/chat/completions", P, req)["body"]["error"]["code"] == "DeploymentNotFound")
check("chat on embedding model -> 400", arm.handle("POST", A + "/openai/deployments/emb/chat/completions", P, req)["status"] == 400)
acct = arm.handle("GET", A, V)["body"]
check("account advertises simulated inference", acct["properties"]["vyomiInference"]["simulated"] is True)
print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
