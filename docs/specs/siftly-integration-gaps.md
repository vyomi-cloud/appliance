---
title: Siftly on Vyomi — integration gaps
status: draft
updated: 2026-10-17
owner: Rohith
compared:
  - Siftly: ~/Downloads/generative-engine-optimization
  - Vyomi: ~/Documents/appliance (v3.0.6)
related:
  - storage-cache-siftly-implementation-plan.md
  - messaging-core-spec.md
  - document-store-spec.md
  - Service Bus emulator spec (Docs): https://claude.ai/code/artifact/34441afa-1058-4193-acf7-deb6f318486b
---

# Siftly on Vyomi — integration gaps

**Bottom line.** Three gaps block Siftly outright: **Service Bus over AMQP**, an **LLM endpoint**, and **AI Search**. Blob Storage and Postgres are partly there. Redis and email are missing but small. Vyomi also lacks three platform pieces Siftly needs: writing an app's `.env`, declaring Siftly's entities in one file, and replaying BrightData so the pipeline has input offline.

Effort is a rough estimate for one engineer who knows the Vyomi codebase. It is not measured. Sizes: **XS** ≤ 1 day · **S** 2–5 days · **M** 1–2 weeks · **L** 3–6 weeks · **XL** > 6 weeks.

## 1. Cloud dependencies

| # | Siftly dependency | What Siftly uses | Existing in Vyomi today | What needs to be done | Effort | Status | Spec |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1a | Azure Service Bus — lease semantics | Peek-lock, `AutoLockRenewer` (up to 1,200 s), complete, abandon, `MessageLockLostError` handling | `core/azure_servicebus_core.py`: topics, subscriptions, fan-out, receive-and-delete, peek-lock, complete, abandon. Locks never expire; no delivery count; no dead-letter; no queues | Extract the SQS core's lease model into a shared module (also used by Pub/Sub) for lock expiry and renewal; add delivery count, max-delivery dead-letter subqueue, queues, 256 KB size limit | M (1–2 wk) | **Blocker** | messaging-core §2 |
| 1b | Azure Service Bus — wire protocol | Python `azure-servicebus` 7.14.3 and JS `@azure/service-bus` 7.9. Both speak AMQP 1.0 only (direct or over WebSockets) | REST wire only. AMQP "out of scope" (CHANGELOG 2.5.0). Microsoft emulator evaluated and rejected (CHANGELOG: .NET-only admin, amd64-only SQL Server sidecar, non-redistributable EULA) | AMQP 1.0 listener on 5671/5672 over the Service Bus core: `$cbs` SAS auth, receive links with credit, dispositions (complete/abandon/dead-letter), `$management` renew-lock, batched transfers, application properties, AMQP error conditions. Test AMQP over WebSockets for the Nano relay | L–XL (5–8 wk) | **Blocker** | Docs spec §SDK compatibility |
| 1c | Azure Service Bus — topology and path | 5 topic/subscription pairs: `scrapper_responses`, partner, LLM analysis, LinkedIn draft, traffic-ingest (names from `AZURE_SERVICEBUS_*` env vars) | Service Bus is on the Nano relay and the opt-in unified ingress, not the default Pro/Max path (CHANGELOG 2.8.1) | Expose on the default Pro/Max path; provision Siftly's 5 pairs from the topology file (row 13) | S (2–3 d) | **Blocker** | messaging-core §7 |
| 2a | LLMs — pass-through gateway | ~25 BAML clients: Azure OpenAI (GPT-4o, o4-mini, GPT-5.x, image), Azure AI Foundry (Claude Sonnet 4.5, DeepSeek V4), OpenAI, Anthropic | Nothing | One endpoint serving Azure OpenAI routes (`/openai/deployments/{d}/…?api-version=`), Foundry OpenAI-compatible `/openai/v1`, OpenAI and Anthropic routes; forwards to real providers; logs tokens and cost | M (1–2 wk) | **Blocker** (workaround: real keys) | Backlog: LLM gateway |
| 2b | LLMs — record/replay | Same | Nothing | Cassettes keyed by provider, model and request hash; replay mode; miss policy (fail or forward); 429 and latency injection | M (1–2 wk) | Needed for offline / zero-cost runs | Backlog: LLM gateway |
| 3 | Azure AI Search | Index `siftly-brand-content`; hybrid keyword + vector (`VectorizedQuery`) + semantic ranking (`services/rag/azure_search_service.py`) | Nothing | Index create and schema; upload, merge, delete documents; keyword search (BM25); vector kNN (pgvector); hybrid fusion (RRF); filters; approximate semantic ranking | L (3–5 wk) | **Blocker for content generation** (workaround: real index) | Backlog: AI Search |
| 4 | Azure Blob Storage | `upload_blob` with `ContentSettings`, `download_blob`, `delete_blob`, `exists`, `create_container(public_access="blob")`, `list_blobs`, `generate_blob_sas` (read) | `core/azure_blob_core.py` + `azure_dataplane.py`: create/list containers, put/get/head/delete blob, prefix listing, content type. Azurite available | SAS URLs, anonymous GET, container `exists` and metadata already work (auth is ignored by design). Remaining: fix content-type precedence and store content headers in all three blob paths (dataplane, portable core, Azurite bridge), public-access level, Azure XML error bodies, SDK verification | S (~3 d solo, ~1.6 d with Claude) | Partial | blob-storage-siftly-spec.md |
| 5 | PostgreSQL | Azure PG **17** + **pgvector** (`halfvec` in `brand_facts`); schema from a prod dump | `postgres:16-alpine`, no pgvector | Keep the **one** existing Postgres 16 server; swap its image for `vyomi/postgres:16-alpine-pgvector` (same base, pgvector compiled in, no migration); `siftly` database with `vector`; restore command that cleans Azure/17-only statements | S (~3 d solo, ~1.75 d with Claude) | Partial | postgres-pgvector-siftly-spec.md |
| 6 | Redis | Cache, locks, rate limits (Azure Cache for Redis in prod) | Nothing | Add `redis:7-alpine`, profile-gated and on-demand, host port 36379 on 127.0.0.1; real provisioner readiness check; write `REDIS_*` and `REDIS_URL` with `REDIS_SSL_ENABLED=false` | S (~2.2 d solo, ~1.25 d with Claude) | Missing, easy | redis-siftly-spec.md |
| 7 | Email | Azure Communication Services email; AWS SES | Nothing | Accept ACS Email REST and SES `SendEmail`; deliver to a local inbox (for example Mailpit) shown in the console | S (3–5 d) | Low priority | — |
| 8 | Key Vault | Deploy scripts only; the app reads env vars | Key Vault Secrets and Keys emulated | Nothing for the dev loop | — | Not needed | — |
| 9 | Container Apps / KEDA | Hosting and scaling | Nothing | Not needed to run Siftly. Only for the scaling simulation | — | Later | messaging-core §6 |

## 2. Non-cloud input the pipeline needs

| # | Dependency | What Siftly uses | Existing in Vyomi today | What needs to be done | Effort | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | BrightData | Scrapes AI answer engines; results arrive by webhook and go onto `scrapper_responses` (`utils/scraper/brightdata_webhook_processor.py`) | Nothing | Record real webhook payloads (pseudonymized); `vyomi replay brightdata` posts them to Siftly's webhook so the pipeline runs offline | S–M (1 wk) | Needed for the core loop |
| 11 | Clerk, Stripe, Reddit, Slack, Firecrawl | Auth, billing, discovery, alerts, crawling | Nothing | Use each provider's test keys. Firecrawl can share the replay mechanism in row 10 | — | Not in scope |

## 3. Vyomi platform gaps

| # | Capability | Existing in Vyomi today | What needs to be done | Effort | Status |
| --- | --- | --- | --- | --- | --- |
| 12 | Write an app's `.env` | `core/env_aliases.py` only maps `CLOUDLEARN_*` ↔ `VYOMI_*` | New generic Go subcommand `vyomi env --map <file>` (does not exist today; the shipped CLI has only up/down/stop/restart/status/logs/update/doctor). The app's repo supplies the map file, so Vyomi contains no app names. It writes `AZURE_SERVICEBUS_CONNECTION_STRING`, `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_SEARCH_*`, `AZURE_OPENAI_*`, `AZURE_ANTHROPIC_ENDPOINT`, DB and Redis vars; shared secrets kept identical across `backend/`, `hocuspocus/`, `siftly-agents-2/` | S–M (1 wk) | Needed |
| 13 | Declare Siftly's entities | Terraform import exists; Siftly provisions with `az` scripts, not Terraform | Topology file (`vyomi.yaml`) for topics/subscriptions, blob containers, search index, databases; applied on `vyomi up` | S (3–5 d) | Needed |
| 14 | Prod-shaped seed data | Snapshots cover console in-process stores only (`core/console_snapshots.py`) | Schema snapshot + FK-aware subset + pseudonymization | L (3–6 wk) | Later (Siftly can keep its prod-subset pull meanwhile) |
| 15 | Fault injection | None; the messaging store has a controllable clock (`set_time`, `advance`) | Fault hooks and scenarios at the MessagingStore seam | M–L | Later |

## 4. Changes on Siftly's side

| # | Change | Where | Effort |
| --- | --- | --- | --- |
| S1 | Start Service Bus workers when `ENVIRONMENT=local` | `backend/main.py:741` | XS |
| S2 | Read the 3 hardcoded Foundry `base_url` values from env | `backend/baml_src/clients.baml` lines 311, 329, 366 | XS |
| S3 | Point edge snippets at the local ingest service | `TRAFFIC_INGEST_SERVICE_URL` in Cloudflare/Vercel snippets | XS |

## 5. Plan and totals

| Step | Rows | What then runs on Vyomi | Effort |
| --- | --- | --- | --- |
| **1. Boots** | 4, 5, 6, 12, 13, 2a (pass-through), S2 | Web app, API, MCP server, Hocuspocus, uploads. LLM calls forwarded to real providers; search on the real index | ~3–5 weeks |
| **2. Core loop** | 1a, 1b, 1c, 10, S1, S3 | Full visibility pipeline, workers, content engine, traffic ingest | ~7–10 weeks |
| **3. Fully offline** | 2b, 3, 7 | Zero-token runs, local RAG, local email | ~5–8 weeks |

Steps 1 and 2 can run in parallel if two people are available: the AMQP listener (1b) is the critical path and touches nothing in step 1.

## 6. Open questions

- [ ] Can AMQP over WebSockets cross the Nano relay, or is Service Bus Pro/Max only?
- [ ] Does Vyomi's `az` support cover `az servicebus` and `az search`, so Siftly's existing provisioning scripts could run unchanged instead of row 13?
- [ ] Do Vyomi's other Postgres-backed services work on Postgres 17?
- [ ] Should the LLM gateway (2a/2b) be a Vyomi service or a separate product surface shared with non-Vyomi users?
