"""Regression: the headless relay endpoint (wasm/relay/nano-endpoint.html, used by test_azure_servicebus_amqp_nano
and the AMQP bridge) must load every core the shared worker loads. aws_wire_router imports the AI-stack cores lazily
(inside _gcp_service), so build_cores.check_relay_cores (load-time imports only) cannot catch a lagging list; the
symptom was HTTP 500 'cannot import name gcp_agentplatform_core' on every request through the endpoint.
Run: PYTHONPATH=. python3 tests/conformance/test_relay_cores_parity.py"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def cores(path):
    t = open(os.path.join(ROOT, path)).read()
    m = re.search(r"const CORES\s*=\s*\[(.*?)\];", t, re.S)
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return set(re.findall(r'"([a-z0-9_]+\.py)"', body))


worker, endpoint = cores("wasm/relay/relay-shared-worker.js"), cores("wasm/relay/nano-endpoint.html")
missing = sorted(worker - endpoint)
lazy = sorted(m for m in ("gcp_agentplatform_core.py", "gcp_agentgov_core.py", "gcp_agentengine_core.py") if m not in endpoint)
print(("[FAIL]" if missing or lazy else "[PASS]"), "nano-endpoint.html CORES covers relay-shared-worker.js CORES", missing or "")
sys.exit(1 if missing or lazy else 0)
