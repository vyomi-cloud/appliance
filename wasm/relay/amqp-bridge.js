// Nano side of the AMQP 1.0 bridge: the relay (local-relay.mjs) accepts AMQP clients (raw TCP :5672 and
// AMQP-over-WebSocket at /$servicebus/websocket) and tunnels each as a numbered stream over the tab's /register
// WebSocket. This module is the tab/worker end: it feeds each stream's bytes into the in-Pyodide AMQP engine
// (core/azure_servicebus_amqp.NanoBridge, installed as builtins _amqp_*) and writes the engine's output back.
//
//   relay -> tab : text  {type:"amqp-open", sid} | {type:"amqp-close", sid}
//                  binary [u32 BE sid][AMQP bytes]
//   tab -> relay : binary [u32 BE sid][AMQP bytes] | text {type:"amqp-close", sid}
//
// createAmqpBridge({ py, send, onActivity, onDirty }) -> { text(msg), binary(arrayBuffer), active(), stop() }
//   send(dataOrString) writes to the relay socket (binary frames are ArrayBuffers).

const b64 = (u8) => {
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
};
const unb64 = (s) => {
  const bin = atob(s), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
};

export function createAmqpBridge({ py, send, onActivity = () => {}, onDirty = () => {}, tickMs = 250 }) {
  const open = new Set();
  let timer = null;
  const fn = (name) => py.globals.get(name);

  function apply(jsonStr) {
    const r = JSON.parse(jsonStr);
    for (const [sid, data] of r.out) {
      const bytes = unb64(data);
      const frame = new Uint8Array(4 + bytes.length);
      new DataView(frame.buffer).setUint32(0, sid);
      frame.set(bytes, 4);
      send(frame.buffer);
    }
    for (const sid of r.close) { open.delete(sid); send(JSON.stringify({ type: "amqp-close", sid })); }
    if (r.out.length) onActivity();
    if (r.dirty) onDirty();
    if (!open.size && timer) { clearInterval(timer); timer = null; }
  }

  function ensureTimer() {
    if (timer) return;
    timer = setInterval(() => { try { apply(fn("_amqp_tick")()); } catch (e) { console.warn("[amqp] tick", e); } }, tickMs);
  }

  return {
    active: () => open.size > 0,
    text(msg) {
      if (msg.type === "amqp-open") { open.add(msg.sid); fn("_amqp_open")(msg.sid); ensureTimer(); return true; }
      if (msg.type === "amqp-close") { open.delete(msg.sid); apply(fn("_amqp_close")(msg.sid)); return true; }
      return false;
    },
    binary(buf) {
      const u8 = new Uint8Array(buf);
      const sid = new DataView(u8.buffer, u8.byteOffset, u8.byteLength).getUint32(0);
      if (!open.has(sid)) return;
      onActivity();
      apply(fn("_amqp_in")(sid, b64(u8.subarray(4))));
    },
    stop() {
      for (const sid of [...open]) { try { fn("_amqp_close")(sid); } catch (_) {} }
      open.clear();
      if (timer) { clearInterval(timer); timer = null; }
    },
  };
}
