---
title: Azure Service Bus for Siftly — prioritised plan
status: draft
updated: 2026-10-17
owner: Rohith
related:
  - servicebus-siftly-implementation-plan.md
  - siftly-integration-gaps.md (rows 1a, 1b, 1c)
  - messaging-core-spec.md
---

# Azure Service Bus for Siftly — prioritised plan

**Goal:** Siftly's workers and senders run unchanged against Vyomi, using `azure-servicebus` 7.14.3 (Python) and `@azure/service-bus` 7.9 (JavaScript), with only a connection-string change and `ENVIRONMENT=local`.

**Today (Vyomi v3.0.6):** `core/azure_servicebus_core.py` serves the Service Bus **REST** wire with topics, subscriptions, fan-out, receive-and-delete, peek-lock, complete and abandon. Its conformance script passes. It runs only on Nano and the opt-in unified ingress (`VYOMI_UNIFIED_INGRESS=1`). Siftly's SDKs speak **AMQP 1.0 only**, so they cannot connect at all.

Effort assumes one engineer who knows Vyomi. "With Claude" assumes Claude writes most of the code and tests, and the engineer reviews, runs the SDKs, and debugs wire captures. All figures are estimates, not measurements.

## What is missing, in priority order

| P | Capability Siftly needs | Today | Change | Solo | With Claude |
| --- | --- | --- | --- | --- | --- |
| 1 | **Shared lease module** | Only the SQS core has a lease model (`visible_at`, receive count, redrive, store clock) | Extract it into one module at the MessagingStore seam: lease with expiry, extend, release, delivery count, max-delivery dead-letter, explicit dead-letter. Port the SQS core onto it with no behaviour change; `test_sqs_fifo_dlq_core` and `test_messaging_core` must stay green | 3–4 d | 1–1.5 d |
| 2 | **Service Bus on the lease module** | Locks never expire; no delivery count; no dead-letter; no renew | Peek-lock uses the module: lock duration per subscription (default 60 s), expiry returns the message, renew from now (lock-lost if expired), `maxDeliveryCount` (default 10) → `<sub>/$DeadLetterQueue` with reason `MaxDeliveryCountExceeded`, explicit dead-letter settlement | 3 d | 1 d |
| 3 | **Pub/Sub on the lease module** (optional; benefits GCP, not on the Siftly path) | No ack deadline, `modifyAckDeadline` or dead-letter policy in the core | Pull uses the module: `ackDeadlineSeconds` (default 10), `modifyAckDeadline` including 0 (= nack), `deliveryAttempt`, dead-letter policy to a topic | 2–3 d | 1 d |
| 4 | **Message properties and limits** | Partial (`BrokerProperties` header) | Round-trip message ID, correlation ID, content type, subject, application properties; enforce 256 KB per message and per batch | 1–2 d | 0.5 d |
| 5 | **Siftly topology** | Created through REST calls | Topology file provisions Siftly's 5 topic/subscription pairs (`scrapper_responses`, partner, LLM analysis, LinkedIn draft, traffic-ingest) on `vyomi up`; state persists on the NATS-backed store | 2 d | 0.5 d |
| 6 | **AMQP 1.0 listener** | None ("out of scope") | Python asyncio server on 5672/5671: frame codec, SASL, open/begin/attach, link credit and flow, transfers (including batched messages), dispositions mapped to complete / abandon / dead-letter. Reuse an MIT-licensed pure-Python AMQP 1.0 codec, such as the one inside `azure-servicebus` (verify licence and fitness first) | 3–4 wk | 1–1.5 wk |
| 7 | **`$cbs` authentication** | None | Accept `put-token` with a SAS token; validate against the topology's key or accept in open mode | 2 d | 0.5 d |
| 8 | **`$management` renew-lock** | None | Request/response link at `<entity>/$management`, operation `com.microsoft:renew-lock`. `AutoLockRenewer` depends on this | 3 d | 1 d |
| 9 | **Azure error conditions** | REST JSON errors only | AMQP errors the SDKs map to their exceptions: `com.microsoft:message-lock-lost`, `amqp:not-found`, `amqp:link:message-size-exceeded`, `com.microsoft:server-busy` | 2 d | 0.5 d |
| 10 | **Connection string and TLS** | None | Plain 5672 with `UseDevelopmentEmulator=true`; TLS 5671 with the local CA for older SDKs; `vyomi env` writes `AZURE_SERVICEBUS_CONNECTION_STRING` | 2 d | 1 d |
| 11 | **Verify with the Python SDK** (test only; no client code is built) | None | Run `azure-servicebus` 7.14.3: topic send (single and batch), subscription receive with `prefetch_count=0` and `max_wait_time`, complete, abandon, `AutoLockRenewer` over 3+ renewals, lock-lost handling | 1 wk | 3–4 d |
| 12 | **Verify with the JS SDK** (test only; no client code is built) | None | Run `@azure/service-bus` 7.9 as `traffic-ingest-service` uses it: `publisher.js` sends to the traffic-ingest topic; `worker.js` receives in peek-lock with `receiveMessages`, then completes or abandons (no lock renewal) | 4–5 d | 2–3 d |
| 13 | **Siftly acceptance in CI** | None | Siftly tests A1–A9 (Docs spec) against Vyomi; Siftly change S1 (`backend/main.py:741`, allow `ENVIRONMENT=local`) | 1 wk | 3 d |
| **Total** | | | | **~8–10 weeks** | **~3.5–4.5 weeks top-down; 4.5–6 weeks bottom-up (23–31 working days)** (see implementation plan) |

Items 1–5 are core changes behind the existing REST wires; the existing conformance scripts catch regressions. Item 1 makes one lease model shared by SQS, Service Bus and Pub/Sub, so Item 3 gives GCP ack deadlines and dead-lettering for about a day of extra work. Items 6–10 add the AMQP front door, which is Azure-only: SQS and SNS speak HTTPS and Pub/Sub speaks REST or gRPC, and Vyomi already serves those. Items 11–12 run Siftly's existing SDKs unchanged against the one Vyomi listener; any other AMQP client (Java, .NET, Go) is the same kind of check, not new server code.

## Why Claude cuts this by about two thirds, and what it does not cut

- **Fast:** the codec, state machine, link handling, error mapping and tests are well-specified code. Claude writes them quickly, from the AMQP 1.0 spec and the SDK source.
- **Not fast:** debugging the real SDKs against the listener. Each mismatch needs a run, a wire capture and a fix, and those loops dominate items 6, 11 and 12. A real Service Bus Standard namespace for comparing traces shortens them a lot.
- **Risk to the estimate:** an SDK behaviour not in the spec, such as a session or settlement mode the SDK insists on. Budget one extra week of contingency.

## Later (not needed for Siftly)

- AMQP over WebSockets, so Nano can serve Service Bus through its relay.
- Queues, sessions, scheduled messages, deferral, peek, SQL filter rules.
- Fault injection (lock-lost, duplicate, throttle) at the MessagingStore seam.

## Verified on 2026-10-17

Ran on the Vyomi repo, host Python 3.10, all passing: `test_messaging_core`, `test_sqs_fifo_dlq_core`, `test_sns_filter_policy_core`, `test_gcp_pubsub_core`, `test_azure_servicebus_core`, `test_azure_queue_core`. These exercise the cores in-process on their native wire shapes; they do not run the cloud SDKs.
