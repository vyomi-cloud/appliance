# v4/azure-sb-amqp

Owner: azure-servicebus-amqp session - Started: 2026-11-10 - Base: origin/v4-on-main - Status: in review

## Purpose
Give Azure Service Bus a real AMQP 1.0 data plane so the NATIVE SDKs (Python `azure-servicebus`, JavaScript `@azure/service-bus`) work unchanged. Before this branch only a Vyomi-invented REST surface existed (`core/azure_servicebus_core.py`); stock SDKs speak AMQP and could not connect. Offline appliance: full AMQP. Nano: the same engine in Pyodide, reached through the local relay as AMQP over TCP / WebSocket. Microsoft's Service Bus emulator stays rejected (amd64 SQL Server, size, EULA) - nothing of it is embedded.

## Architecture
```
 native SDK ──AMQP/TCP :5672──┐                     ┌─ core/amqp_server.py (asyncio, sniffs AMQP vs HTTP-Upgrade)
            ──AMQP/WS /$servicebus/websocket──────►─┤        │ bytes
            ──AMQPS :5671 (self-signed)───────────┘         ▼
                                                     core/amqp10.py          protocol engine (codec, SASL, connection/session/link, flow, settlement)
                                                         │ Container callbacks
                                                         ▼
                                                     core/azure_servicebus_amqp.py   Service Bus dialect + broker
                                                         │ + core/azure_servicebus_rules.py (SQL / correlation filters)
                                                         ▼
                                                     MessagingStore.topics   ← the SAME dicts core/azure_servicebus_core.py (REST / console Explorer) uses

 Nano:  SDK ─TCP :5672 / ws ─► wasm/relay/local-relay.mjs ──(numbered stream over the tab's /register socket)──► tab
        tab: wasm/relay/amqp-bridge.js ──base64──► Pyodide: core/azure_servicebus_amqp.NanoBridge ──► router.az_sb (InMemory registry store)
```
- `core/amqp10.py` is substrate-free (bytes in, bytes out; no sockets / asyncio / threads) and loads under Pyodide. It implements the type codec, frames, SASL server (ANONYMOUS/PLAIN/EXTERNAL/MSSBCBS accepted), connection/session/link state machines, link credit + drain, session windows, multi-frame transfers both ways, idle-timeout keep-alives, and a `Container` callback interface.
- `core/azure_servicebus_amqp.py` is the dialect: `$cbs` put-token, entity addressing (`q`, `topic/Subscriptions/sub`, `.../$DeadLetterQueue`, `.../$management`), lock tokens as delivery tags (UUID bytes_le), `x-opt-*` annotations, settlement mapping (accepted=complete, released/modified=abandon, modified+undeliverable=defer, rejected=dead-letter), lock expiry, MaxDeliveryCount, TTL, scheduled messages, duplicate detection, sessions, batch message format 0x80013700, and the `$management` operations the SDKs use. `NanoBridge` is the Pyodide glue (one `Connection` per relay stream id).
- Entity state extends the REST core's dicts: `messages`, `dead_letter`, `scheduled`, `rules`, `_slocks`, `_sstate`, options `lock_duration`, `max_delivery_count`, `requires_session`, ... and per-message `_wire` (the byte-exact encoded properties + application-properties + body), `_anns`, `_enq`, `_expires`, `_session`, `_lock_until`, `_lock_link`. REST-created messages have no `_wire`; one is synthesised on delivery. REST `PUT` accepts an optional JSON body with the entity options (and REST sends now honour subscription rules).
- Offline wiring: `routes/azure_servicebus_amqp.py` (registered from `server.py`) starts the listener on app startup; ports `VYOMI_AMQP_PORT` (5672) / `VYOMI_AMQPS_PORT` (5671), `0` disables; compose publishes both. State persists through the existing debounced state flush.
- Nano wiring: `local-relay.mjs` adds a raw-TCP listener (`RELAY_AMQP_PORT`, default 5672) and an upgrade route for any path ending `/$servicebus/websocket`; both become streams on the registered tab socket (text `amqp-open`/`amqp-close`, binary `[u32 sid][bytes]`). `nano-endpoint.html` and `relay-shared-worker.js` hand them to `amqp-bridge.js`. The three core lists and `wasm/build_cores.py` vendor `amqp10.py`, `azure_servicebus_rules.py`, `azure_servicebus_amqp.py`.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Own pure-Python AMQP engine | python-qpid-proton / Apache Qpid broker; Microsoft emulator | Must run in Pyodide (no C extension, no sockets) and on a store shared with REST; the emulator is not viable (amd64 SQL, size, EULA). |
| Engine and dialect are separate modules | One broker file | The engine is reusable for other AMQP services and has no Service Bus knowledge; the dialect has no byte handling. |
| Bind to the existing `MessagingStore.topics` dicts | A new AMQP-only store | Requirement: REST Explorer and AMQP clients see one state; also gets persistence, Nano registry sync and CMK sealing for free. |
| Keep each message's wire image (`_wire`) | Re-encode from the REST fields | Byte-exact round trip of properties / application properties / body types for every SDK. The CMK scope seals `_wire` together with `body`. |
| Pump on a 250 ms timer plus after every inbound frame | Event-driven only | REST sends and timers (lock expiry, TTL, scheduled) change state outside any AMQP connection; one pump keeps receivers fed. |
| Credentials, claims and tenants are not verified | Verify SAS signatures | Same stance as the REST core; the simulator is not a security boundary. |
| Reply to an unsettled rejected disposition with `rejected` WITHOUT the error | Echo the error | The 7.15 Python SDK reads a rejected outcome that carries an error as "failed to apply". |
| Nano AMQP only through the local relay | Cloudflare Durable Object relay now | A long-lived binary stream per connection needs DO WebSocket plumbing; the local relay is the supported developer path and keeps Pyodide as the engine. |
| Base64 across the JS/Pyodide boundary | Pyodide buffer proxies | Simple and robust; costs ~33 % on large messages (600 KB message verified). |
| Raw TCP listener and WS on one offline port by sniffing the first bytes | Two ports | One firewall/compose entry; the SDKs' WebSocket transport targets the same host:port. |

## Open issues
- [ ] Cloudflare cloud relay (`wasm/relay/worker.js`) does not bridge AMQP streams; `relay.vyomi.cloud` users cannot use AMQP yet. The in-page, relay-less Nano boot cannot (no socket).
- [ ] Real-browser verification: the Nano path was exercised headlessly (real local relay + Pyodide in Node + the real `AwsWireRouter`), not in a Chrome tab / the shared worker.
- [ ] TLS: AMQPS on :5671 uses a self-signed cert; no SDK was run over it (SDKs would need the cert trusted). Handshake verified with a raw client only. No TLS on Nano.
- [ ] `SAS`/Entra verification, claims (Send/Listen/Manage) and namespace network rules are not enforced on AMQP.
- [ ] ARM-created queues/topics are not mirrored into the data store; entities used over AMQP must be created via the REST data plane / console. `ServiceBusAdministrationClient` (ATOM XML) is not served.
- [ ] Not modelled: partitions, auto-forward, transactions, geo-DR failover on AMQP, per-tier size limits, `batch-delete-messages`, per-entity sequence numbers (global to the store), per-namespace isolation (names global).
- [ ] CMK path: the broker runs inside `CmkScope` when a CMK namespace exists, but no native-SDK test covers a CMK namespace over AMQP.
- [ ] Session locks do not expire while the receiver link is open.
- [ ] Console: nothing changed; the Explorer's session / scheduled counters still read zero.

## Testing
All with the unchanged SDKs (scratch venv / npm outside the repo; set `VYOMI_SB_JS_NODE_MODULES`):
- `tests/conformance/test_azure_servicebus_amqp_python_sdk.py` - 19 tests, offline TCP: send/receive/complete, properties round trip, abandon, dead-letter + DLQ read, defer + receive-deferred, receive-and-delete, peek, batch, schedule/cancel, lock expiry/renew, max-delivery-count, TTL dead-lettering, duplicate detection, sessions (named, next-available, state, lock conflict), topic fan-out, REST<->AMQP shared state, entity-not-found, `$cbs` path with a credential, 700 KB multi-frame message.
- `tests/conformance/test_azure_servicebus_amqp_js_sdk.py` + `servicebus_amqp_js_sdk.cjs` - 12 checks x {offline TCP, offline WebSocket, Nano TCP, Nano WebSocket}, including streaming `subscribe`, sessions, and `ruleManager` SQL/correlation rules with fan-out.
- `tests/conformance/test_azure_servicebus_amqp_nano.py` - Python SDK against the Nano fixture (`wasm/relay/test-amqp-bridge.mjs`: real relay + Pyodide + real router).
- Regression: `test_azure_servicebus_core.py` and `test_azure_cmk_enforced.py` (run with `PYTHONPATH=.`), `node consoles/tests/nano-core-import-check.mjs` (265 modules, 0 failures).
- The real appliance store was exercised with the unified REST route + the AMQP route on Python 3.9 (server.py needs >= 3.10): AMQP send visible to REST peek, REST send received over AMQP.
