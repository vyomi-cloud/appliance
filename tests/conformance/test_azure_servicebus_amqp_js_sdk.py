"""The REAL JavaScript `@azure/service-bus` SDK against the simulator's Service Bus AMQP data plane (TCP, and
AMQP-over-WebSocket). Skips cleanly when node or the SDK is not available.

Point it at an install with:  VYOMI_SB_JS_NODE_MODULES=/path/to/node_modules  (must contain @azure/service-bus and ws)
Run:  python3 -m pytest tests/conformance/test_azure_servicebus_amqp_js_sdk.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

from tests.conformance._sb_amqp_harness import Broker

HERE = os.path.dirname(__file__)
SCRIPT = os.path.join(HERE, "servicebus_amqp_js_sdk.cjs")


def _node_modules():
    cands = [os.environ.get("VYOMI_SB_JS_NODE_MODULES"), os.path.join(HERE, "node_modules"),
             os.path.join(os.getcwd(), "node_modules")]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "@azure", "service-bus")):
            return c
    return None


pytestmark = pytest.mark.skipif(not shutil.which("node") or not _node_modules(),
                                reason="node or @azure/service-bus not installed (set VYOMI_SB_JS_NODE_MODULES)")


def _entities(b):
    ents = {"queue": "jq", "dlqQueue": "jdlq", "maxDeliveryQueue": "jmax", "sessionQueue": "jsess", "topic": "jtopic",
            "subAll": "all", "subSql": "sql", "subCorr": "corr", "subNone": "none"}
    b.create("jq")
    b.create("jdlq")
    b.create("jmax", maxDeliveryCount=2)
    b.create("jsess", requiresSession=True)
    b.create("jtopic")
    for s in ("all", "sql", "corr", "none"):
        b.create_sub("jtopic", s)
    return ents


def _run(args, extra_env=None):
    env = dict(os.environ, NODE_PATH=_node_modules(), **(extra_env or {}))
    p = subprocess.run(["node", SCRIPT] + args, capture_output=True, text=True, timeout=240, env=env)
    return p.returncode, p.stdout + p.stderr


def _assert_all_ok(rc, out):
    fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    assert rc == 0 and not fails, "\n".join(fails) or out[-2000:]
    assert sum(1 for ln in out.splitlines() if ln.startswith("ok ")) >= 10


def test_js_sdk_over_tcp():
    b = Broker().start()
    try:
        ents = _entities(b)
        rc, out = _run([b.conn_str, json.dumps(ents)])
        print(out)
        _assert_all_ok(rc, out)
    finally:
        b.stop()


def test_js_sdk_over_websocket():
    """AMQP-over-WebSocket (the SDK's webSocketOptions transport): the SDK dials wss://host/$servicebus/websocket;
    the test wrapper only re-targets that URL at the simulator's plain ws listener (no TLS terminator in the harness)."""
    b = Broker().start()
    try:
        ents = _entities(b)
        rc, out = _run([b.conn_str, json.dumps(ents), "ws://127.0.0.1:%d/$servicebus/websocket" % b.port])
        print(out)
        _assert_all_ok(rc, out)
    finally:
        b.stop()
