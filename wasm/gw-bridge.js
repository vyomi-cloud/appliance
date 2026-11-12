/* Browser half of the Nano gateway data plane (docs/architecture/v4.0/GATEWAY-NANO-FORWARDING.md).
 *
 * The API Gateway engine runs in Pyodide and cannot open a socket. core/gcp_apigateway_gateway.ahandle() awaits
 * `globalThis.vyomiBackendFetch(json)` — installed here — which sends the backend call to:
 *   1. the user's LOCAL tunnel:  GET <local>/gw-token  then  POST <local>/gw-egress   (only origins mapped with `vyomi-tunnel gateway-backend`)
 *   2. else the HOSTED relay:    POST https://relay.vyomi.cloud/gw-egress             (public https backends on its allow-list, needs the Nano session)
 * Returns a JSON string {status, headers, body(base64)} or {error}. Never throws into Python.
 *
 * Installed by every context that serves the wire: nano-boot.js (the in-page /_wire path), relay-shared-worker.js and nano-endpoint.html
 * (the relay path). Chrome asks the user once for the page -> 127.0.0.1 Private Network Access prompt (accepted, owner decision 2026-11-12).
 */
const DEFAULT_LOCAL = "http://127.0.0.1:8090";
const DEFAULT_HOSTED = "https://relay.vyomi.cloud";
const ls = (k) => { try { return globalThis.localStorage && localStorage.getItem(k); } catch (_) { return null; } };

export function installGatewayBridge(opts = {}) {
  if (globalThis.vyomiBackendFetch && !opts.force) return globalThis.vyomiBackendFetch;
  const local = () => String(opts.local ? opts.local() : (ls("nano_local_ext") || DEFAULT_LOCAL)).replace(/\/$/, "");
  const hosted = () => String(opts.hosted ? opts.hosted() : DEFAULT_HOSTED).replace(/\/$/, "");
  const session = () => (opts.session ? opts.session() : ls("nano_session")) || "";
  const timeoutOf = (req) => Math.min(45000, Math.max(2000, (Number(req.timeout) || 15) * 1000 + 3000));
  let token = null;

  async function viaLocal(payload, req) {
    const base = local();
    if (!token) {
      let r; try { r = await fetch(base + "/gw-token", { signal: AbortSignal.timeout(2500) }); } catch (_) { return { skip: "no local tunnel" }; }
      if (r.status === 501) return { skip: "the local relay has gateway egress off" };
      if (!r.ok) return { skip: "the local relay refused this page (HTTP " + r.status + ")" };
      token = (await r.json()).token;
    }
    let r;
    try { r = await fetch(base + "/gw-egress", { method: "POST", headers: { "content-type": "application/json", "x-vyomi-gw-token": token }, body: payload, signal: AbortSignal.timeout(timeoutOf(req)) }); }
    catch (_) { token = null; return { skip: "local tunnel unreachable" }; }
    if (r.status === 401) { token = null; return { skip: "stale tunnel token" }; }   // relay restarted: next call refetches it
    const j = await r.json().catch(() => ({}));
    return { status: r.status, json: j };
  }
  async function viaHosted(payload, req) {
    const sid = session();
    if (!sid) return { error: "no Nano session id for the hosted relay" };
    let r;
    try { r = await fetch(hosted() + "/gw-egress", { method: "POST", headers: { "content-type": "application/json", "x-vyomi-session": sid }, body: payload, signal: AbortSignal.timeout(timeoutOf(req)) }); }
    catch (e) { return { error: "hosted relay unreachable" }; }
    return { status: r.status, json: await r.json().catch(() => ({})) };
  }
  const ok = (j) => j && typeof j.status === "number" && typeof j.body === "string";

  globalThis.vyomiBackendFetch = async (reqJson) => {
    let req; try { req = JSON.parse(reqJson); } catch (_) { return JSON.stringify({ error: "bad request" }); }
    const payload = JSON.stringify({ method: req.method, url: req.url, headers: req.headers, body: req.body, timeout: req.timeout });
    let backendHost = ""; try { backendHost = new URL(req.url).origin; } catch (_) {}
    const l = await viaLocal(payload, req);
    if (l.json && ok(l.json)) return JSON.stringify(l.json);
    // A mapped backend that failed (timeout, refused, too large) is answered by the local relay; do not retry it elsewhere.
    if (l.json && l.json.code && l.json.code !== "not-mapped") return JSON.stringify({ error: l.json.error || l.json.code });
    const publicHttps = /^https:/.test(req.url || "");
    if (publicHttps) {
      const h = await viaHosted(payload, req);
      if (h.json && ok(h.json)) return JSON.stringify(h.json);
      if (h.json && h.json.error) {
        const hint = l.skip ? ` To reach a backend on your own machine, run \`vyomi-tunnel gateway-backend ${backendHost}=http://127.0.0.1:<port>\`.` : "";
        return JSON.stringify({ error: (l.json && l.json.code === "not-mapped" ? `${backendHost} is not mapped in your local tunnel and the hosted relay refused it (${h.json.error}).` : `hosted relay: ${h.json.error}.`) + hint });
      }
      if (h.error && !l.json) return JSON.stringify({ error: `${l.skip || "no local tunnel"}; ${h.error}. Run \`vyomi-tunnel\` and \`vyomi-tunnel gateway-backend ${backendHost}=<local origin>\`.` });
    }
    if (l.json && l.json.code === "not-mapped") return JSON.stringify({ error: l.json.error });
    return JSON.stringify({ error: `the backend cannot be reached from Nano (${l.skip || "no route"}). Run \`vyomi-tunnel\` and \`vyomi-tunnel gateway-backend ${backendHost || "<https origin>"}=<local origin>\`.` });
  };
  return globalThis.vyomiBackendFetch;
}
