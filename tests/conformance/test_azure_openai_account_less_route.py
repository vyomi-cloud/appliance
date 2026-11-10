"""The console chat playground calls the Azure OpenAI data plane WITHOUT an account (/openai/deployments/<dep>/chat/completions).
That request carries no provider marker, so it must still resolve the AZURE space's ARM records (the account + deployment the
console created); regression: it ran as the default (AWS) provider and returned DeploymentNotFound for an existing deployment.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_openai_account_less_route.py   (or pytest)"""
import json
import os
import sys
import tempfile

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="az-openai-acctless-"))   # hermetic: never the real state
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from core import app_context as ctx          # noqa: E402
from core import llm_core                    # noqa: E402
from core import wire_ingress                # noqa: E402
from providers import azure_services         # noqa: E402

llm_core.set_backend(lambda m, sy, mt, t, st: {"text": "mesh ok"})


def _call():
    ctx.init_azure_state()
    t = ctx.REQUEST_PROVIDER.set("azure")        # how the ARM route stores the records the console creates
    try:
        rid = "/subscriptions/s/resourcegroups/rg/providers/microsoft.cognitiveservices/accounts/acct1"
        azure_services._state[rid] = {"id": rid, "name": "acct1", "_type": "microsoft.cognitiveservices/accounts", "kind": "OpenAI",
                                      "properties": {}, "_deployments": {"my-model": {"name": "my-model", "properties": {
                                          "model": {"format": "OpenAI", "name": "gpt-4o", "version": "1"},
                                          "capabilities": {"chatCompletion": "true"}}}}}
    finally:
        ctx.REQUEST_PROVIDER.reset(t)
    r = wire_ingress.appliance_router()          # the request itself runs under the DEFAULT provider, as /_wire/openai does
    body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}).encode()
    return r.handle("POST", "/openai/deployments/my-model/chat/completions?api-version=2024-10-21", {"api-version": "2024-10-21"},
                    {"api-key": "x", "content-type": "application/json"}, body)


def _status(out):
    return out.get("status") if isinstance(out, dict) else getattr(out, "status", None)


def test_account_less_openai_route_resolves_the_azure_space():
    out = _call()
    assert _status(out) == 200, out


if __name__ == "__main__":
    o = _call()
    print(("[PASS]" if _status(o) == 200 else "[FAIL]"), "account-less /openai route sees the ARM-created deployment", _status(o), str(o)[:200])
    sys.exit(0 if _status(o) == 200 else 1)
