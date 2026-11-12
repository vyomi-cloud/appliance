/* Nano AMQP bridge fixture: a headless stand-in for the Nano tab, for tests/conformance/test_azure_servicebus_amqp_nano.py.
 *
 *   starts  : the REAL local relay (wasm/relay/local-relay.mjs) on RELAY_PORT with its raw-AMQP listener on RELAY_AMQP_PORT
 *   boots   : the vendored Pyodide in Node, mounts the SAME core list the Nano loaders use, builds the REAL AwsWireRouter
 *             and installs NanoBridge on its Service Bus store (exactly what nano-endpoint.html / relay-shared-worker.js do)
 *   connects: to the relay's /register as a tab, answering HTTP requests through the router and AMQP streams through
 *             wasm/relay/amqp-bridge.js
 *   prints  : "READY <relay-port> <amqp-port>" then runs until killed.
 *
 *   python3 wasm/fetch_pyodide.py && python3 wasm/build_cores.py
 *   NODE_PATH=<dir with ws> RELAY_PORT=18090 RELAY_AMQP_PORT=15673 node wasm/relay/test-amqp-bridge.mjs
 */
import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join, dirname } from "node:path";
import { createRequire } from "node:module";
import { createAmqpBridge } from "./amqp-bridge.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const W = join(HERE, "..");
const RELAY_PORT = process.env.RELAY_PORT || "18090";
const AMQP_PORT = process.env.RELAY_AMQP_PORT || "15673";
const { WebSocket } = createRequire(import.meta.url)(process.env.WS_PKG || "ws");

const list = (file, name) => {
  const m = readFileSync(join(W, file), "utf8").match(new RegExp(`const ${name}\\s*=\\s*\\[(.*?)\\];`, "s"));
  return m ? [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]) : [];
};
const cores = list("relay/nano-endpoint.html", "CORES");
const pkgs = list("relay/nano-endpoint.html", "CORE_PKGS");

const relay = spawn(process.execPath, [join(HERE, "local-relay.mjs")], {
  env: { ...process.env, RELAY_PORT, RELAY_AMQP_PORT: AMQP_PORT }, stdio: ["ignore", "inherit", "inherit"],
});
const stop = () => { try { relay.kill(); } catch (_) {} process.exit(0); };
process.on("SIGTERM", stop); process.on("SIGINT", stop);
process.on("exit", () => { try { relay.kill(); } catch (_) {} });

const { loadPyodide } = await import(pathToFileURL(join(W, "vendor/pyodide/pyodide.mjs")).href);
const py = await loadPyodide({ indexURL: join(W, "vendor/pyodide") + "/" });
try { await py.loadPackage("sqlite3"); } catch (_) {}
try { await py.loadPackage("tzdata"); } catch (_) {}
const put = (p, src) => { py.FS.mkdirTree(dirname(p)); py.FS.writeFile(p, src); };
py.FS.mkdirTree("/core"); py.FS.writeFile("/core/__init__.py", "");
for (const c of [...cores, ...pkgs]) put("/core/" + c, readFileSync(join(W, "core", c), "utf8"));
py.globals.set("_USE_PGLITE", false);
py.runPython(`
import sys, json, base64, builtins; sys.path.insert(0, "/")
from core.aws_wire_router import AwsWireRouter
from core import nano_registry as _reg
_STORES = _reg.get()
_ROUTER = AwsWireRouter(stores=_STORES)
from core.azure_servicebus_amqp import NanoBridge as _NanoBridge
_NanoBridge.install(lambda: _ROUTER.az_sb)
async def _handle(req_json):
    r = json.loads(req_json)
    body = base64.b64decode(r.get("body") or "")
    resp = await _ROUTER.ahandle(r["method"], r["path"], r.get("query") or {}, r.get("headers") or {}, body)
    return json.dumps({"status": resp["status"], "headers": resp["headers"], "body": base64.b64encode(resp["body"] or b"").decode()})
builtins._handle = _handle
`);
const handle = (reqJson) => py.runPythonAsync(`await _handle(${JSON.stringify(reqJson)})`);

let sock = null;
const bridge = createAmqpBridge({ py, send: (d) => { try { sock && sock.send(d); } catch (_) {} } });
await new Promise((resolve, reject) => {
  sock = new WebSocket(`ws://127.0.0.1:${RELAY_PORT}/register`);
  sock.binaryType = "arraybuffer";
  sock.on("open", resolve); sock.on("error", reject);
  sock.on("message", async (data, isBinary) => {
    if (isBinary) { try { bridge.binary(data); } catch (e) { console.error("amqp:", e); } return; }
    const req = JSON.parse(data.toString());
    if (req.type === "ping") { sock.send(JSON.stringify({ type: "pong" })); return; }
    if (req.type === "amqp-open" || req.type === "amqp-close") { try { bridge.text(req); } catch (e) { console.error("amqp:", e); } return; }
    try { sock.send(JSON.stringify({ id: req.id, ...JSON.parse(await handle(JSON.stringify(req))) })); }
    catch (e) { sock.send(JSON.stringify({ id: req.id, status: 500, headers: {}, body: Buffer.from(String(e)).toString("base64") })); }
  });
});
console.log(`READY ${RELAY_PORT} ${AMQP_PORT}`);
