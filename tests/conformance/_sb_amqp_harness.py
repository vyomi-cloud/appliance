"""Test harness: run the Service Bus AMQP 1.0 broker (core/azure_servicebus_amqp.py) over a real TCP socket
on a free port, in a background event-loop thread, bound to an InMemoryMessagingStore the REST core
(core/azure_servicebus_core.py) shares. Native Service Bus SDKs then connect to it unchanged."""
import asyncio
import socket
import threading

from core import azure_servicebus_core as sb
from core.amqp_server import AmqpServer
from core.azure_servicebus_amqp import ServiceBusAmqp
from core.messaging_store import InMemoryMessagingStore


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Broker:
    def __init__(self, store=None):
        self.store = store or InMemoryMessagingStore()
        self.container = ServiceBusAmqp(lambda: self.store)
        self.server = AmqpServer(self.container)
        self.port = free_port()
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.server.start("127.0.0.1", self.port))
        self._ready.set()
        self.loop.run_forever()

    def start(self):
        self.thread.start()
        assert self._ready.wait(10), "broker did not start"
        return self

    def stop(self):
        fut = asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
        try:
            fut.result(5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)

    # REST data plane on the SAME store (what the console explorer uses)
    def rest(self, method, path, body=b"", headers=None):
        return sb.dispatch(self.store, method, path, {}, headers or {}, body)

    def create(self, name, **opts):
        import json
        self.rest("PUT", "/" + name, json.dumps(opts).encode() if opts else b"")

    def create_sub(self, topic, sub, **opts):
        import json
        self.rest("PUT", "/%s/subscriptions/%s" % (topic, sub), json.dumps(opts).encode() if opts else b"")

    @property
    def conn_str(self):
        return "Endpoint=sb://localhost:%d;SharedAccessKeyName=k;SharedAccessKey=v;UseDevelopmentEmulator=true" % self.port

    @property
    def ws_url(self):
        return "ws://127.0.0.1:%d/$servicebus/websocket" % self.port


class NanoBroker:
    """The Nano substrate: the real local relay + a headless Nano tab (Pyodide + the real AwsWireRouter) from
    wasm/relay/test-amqp-bridge.mjs. Native SDKs dial the relay's raw AMQP listener / its /$servicebus/websocket path;
    entities are created through the relay's HTTP surface (the same namespace-root REST data plane Nano serves)."""

    def __init__(self):
        import os
        import subprocess
        here = os.path.dirname(os.path.abspath(__file__))
        self.script = os.path.join(here, "..", "..", "wasm", "relay", "test-amqp-bridge.mjs")
        self.http_port, self.port = free_port(), free_port()
        self.node_modules = os.environ.get("VYOMI_SB_JS_NODE_MODULES", "")
        self.proc = subprocess.Popen(
            ["node", self.script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=dict(os.environ, RELAY_PORT=str(self.http_port), RELAY_AMQP_PORT=str(self.port), NODE_PATH=self.node_modules))
        self.log = []

    def start(self, timeout=240):
        import threading
        import time
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self.proc.stdout.readline()
            if not line:
                break
            self.log.append(line)
            if line.startswith("READY"):
                threading.Thread(target=lambda: [self.log.append(x) for x in self.proc.stdout], daemon=True).start()
                return self
        raise RuntimeError("Nano fixture did not become ready:\n" + "".join(self.log[-20:]))

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except Exception:
            self.proc.kill()

    def _http(self, method, path, body=b"", headers=None):
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.http_port, path), data=body or None, method=method,
                                     headers=dict({"BrokerProperties": "{}"}, **(headers or {})))
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()

    def create(self, name, **opts):
        import json
        self._http("PUT", "/" + name, json.dumps(opts).encode() if opts else b"")

    def create_sub(self, topic, sub, **opts):
        import json
        self._http("PUT", "/%s/subscriptions/%s" % (topic, sub), json.dumps(opts).encode() if opts else b"")

    def peek(self, name):
        import json
        return json.loads(self._http("GET", "/%s/messages" % name)[1])["messages"]

    @property
    def conn_str(self):
        return "Endpoint=sb://localhost:%d;SharedAccessKeyName=k;SharedAccessKey=v;UseDevelopmentEmulator=true" % self.port

    @property
    def ws_url(self):
        return "ws://127.0.0.1:%d/$servicebus/websocket" % self.http_port
