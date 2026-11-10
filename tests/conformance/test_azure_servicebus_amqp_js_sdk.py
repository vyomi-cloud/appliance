"""The REAL JavaScript `@azure/service-bus` SDK against the simulator's Service Bus AMQP data plane, on both substrates:
  offline : asyncio TCP + AMQP-over-WebSocket listener (core/amqp_server.py)
  Nano    : the relay's raw-TCP listener and /$servicebus/websocket path, bridged into the Pyodide engine
            (wasm/relay/test-amqp-bridge.mjs: real relay + headless tab + real AwsWireRouter)
Skips cleanly when node, the SDK, or (Nano) the vendored Pyodide is not available.

Point it at an install with:  VYOMI_SB_JS_NODE_MODULES=/path/to/node_modules  (must contain @azure/service-bus and ws)
Nano needs:  python3 wasm/fetch_pyodide.py && python3 wasm/build_cores.py
Run:  python3 -m pytest tests/conformance/test_azure_servicebus_amqp_js_sdk.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

from tests.conformance._sb_amqp_harness import Broker, NanoBroker

HERE = os.path.dirname(__file__)
SCRIPT = os.path.join(HERE, "servicebus_amqp_js_sdk.cjs")
PYODIDE = os.path.join(HERE, "..", "..", "wasm", "vendor", "pyodide", "pyodide.mjs")


def _node_modules():
    cands = [os.environ.get("VYOMI_SB_JS_NODE_MODULES"), os.path.join(HERE, "node_modules"),
             os.path.join(os.getcwd(), "node_modules")]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "@azure", "service-bus")):
            return c
    return None


pytestmark = pytest.mark.skipif(not shutil.which("node") or not _node_modules(),
                                reason="node or @azure/service-bus not installed (set VYOMI_SB_JS_NODE_MODULES)")


def _entities(b, sfx):
    """fresh entity names per run (a substrate fixture is shared by the tcp + ws runs)"""
    e = {"queue": "jq" + sfx, "dlqQueue": "jdlq" + sfx, "maxDeliveryQueue": "jmax" + sfx, "sessionQueue": "jsess" + sfx,
         "topic": "jtopic" + sfx, "subAll": "all", "subSql": "sql", "subCorr": "corr", "subNone": "none"}
    b.create(e["queue"])
    b.create(e["dlqQueue"])
    b.create(e["maxDeliveryQueue"], maxDeliveryCount=2)
    b.create(e["sessionQueue"], requiresSession=True)
    b.create(e["topic"])
    for s in ("all", "sql", "corr", "none"):
        b.create_sub(e["topic"], s)
    return e


def _run(args):
    env = dict(os.environ, NODE_PATH=_node_modules())
    p = subprocess.run(["node", SCRIPT] + args, capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, p.stdout + p.stderr


def _assert_all_ok(rc, out):
    fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    assert rc == 0 and not fails, "\n".join(fails) or out[-2000:]
    assert sum(1 for ln in out.splitlines() if ln.startswith("ok ")) >= 12


@pytest.fixture(scope="module")
def offline():
    b = Broker().start()
    yield b
    b.stop()


@pytest.fixture(scope="module")
def nano():
    if not os.path.exists(PYODIDE):
        pytest.skip("wasm/vendor/pyodide missing (python3 wasm/fetch_pyodide.py)")
    os.environ.setdefault("VYOMI_SB_JS_NODE_MODULES", _node_modules())
    b = NanoBroker().start()
    yield b
    b.stop()


@pytest.mark.parametrize("sub,transport", [("offline", "tcp"), ("offline", "ws"), ("nano", "tcp"), ("nano", "ws")])
def test_js_sdk(request, sub, transport):
    b = request.getfixturevalue(sub)
    ents = _entities(b, "-" + transport)
    args = [b.conn_str, json.dumps(ents)] + ([b.ws_url] if transport == "ws" else [])
    rc, out = _run(args)
    print(out)
    _assert_all_ok(rc, out)
