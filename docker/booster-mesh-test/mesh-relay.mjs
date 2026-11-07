// Minimal relay for the mesh harness: only the /mesh plane (the real relay wires the same hub in wasm/relay/local-relay.mjs).
import http from "node:http";
import { createRequire } from "node:module";
import { createMeshHub } from "/opt/relay/booster-mesh.mjs";
const { WebSocketServer } = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
const hub = createMeshHub({ WebSocketServer, log: (m) => console.log("[relay] " + m) });
const srv = http.createServer((req, res) => { if (!hub.http(req, res)) { res.writeHead(404); res.end(); } });
srv.on("upgrade", (req, socket, head) => { if (req.url.split("?")[0] === "/mesh") hub.upgrade(req, socket, head); else socket.destroy(); });
srv.listen(8787, "0.0.0.0", () => console.log("[relay] listening 8787"));
process.on("SIGTERM", async () => { await hub.close(); process.exit(0); });
