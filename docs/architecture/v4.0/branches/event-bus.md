# v4/event-bus

Owner: event-bus session - Started: 2026-11-12 - Base: origin/v4-on-main (ab60bba7f) - Status: in progress

## Purpose
V4.0.0-BLOCKERS item 1 (event-bus half): one real, shared, substrate-free event-bus engine for Eventarc, EventBridge and Event Grid.

## Architecture
- `core/event_bus_engine.py`: stdlib-only engine, all I/O injected (`deliver(target, event[, ctx])`, `clock`, `sleep`). Subscriptions + generic filters,
  CloudEvents envelope, delivery with exponential-backoff retries, max attempts, dead-letter target, strict per-(subscription, ordering key) FIFO lanes,
  JSON-serialisable delivery log with per-attempt history. First attempt inline; retries by `tick()` (daemon pump thread where threads exist, lazy tick on
  every Eventarc API call otherwise, e.g. Nano). `sync` policies retry inline (EventBridge, Event Grid).
- Eventarc (`core/gcp_eventarc_core.py`): `deliver()` hands each matching trigger to the engine (state in `store.ext["eventarc_bus"]`); new `httpEndpoint`
  destination, `retryPolicy`, `deadLetterTopic` (Pub/Sub); `/deliveries` returns attempt history; console detail page shows it.
- EventBridge (`_deliver_with_retry`) and Event Grid (`_attempt_delivery`) dispatch through the same engine with sync policies.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Engine does not own cloud-specific matching/targets | one monolithic bus with per-cloud rule syntax | each cloud keeps its wire semantics; only delivery policy is shared |
| Inline first attempt, async retries | fully async queue | existing tests/consoles expect the first outcome immediately |
| `inflight` flag on a delivery | separate bus instance per cloud | re-entrant ticks (target -> another bus) must not re-attempt a delivery in progress |

## Open issues
- [ ] EventBridge/Event Grid keep their sync (inline, capped) retries: no wall-clock backoff window, no persisted history across restarts.
- [ ] Event Grid webhook validation handshake, Lambda/Function targets via the engine's wall-clock mode, Nano tunnel path not exercised.
- [ ] `gcp-v4-roundtrip.mjs` / `gcp-validation.mjs` (browser suites) not run in this session.

## Testing
tests/conformance/test_event_bus_engine.py (real local HTTP receiver: retries, DLQ, ordering, Eventarc via the wire router, Event Grid), plus the existing
Eventarc / Cloud Run / EventBridge / Event Grid conformance suites.
