---
title: Siftly on Vyomi — what runs today and what is still missing
status: living document
updated: 2026-10-19
owner: Rohith
related:
  - siftly-integration-gaps.md (the original gap analysis)
  - siftly-on-vyomi-test-plan.md
  - app-env-spec.md, servicebus-siftly-plan.md, blob-storage-siftly-spec.md,
    redis-siftly-spec.md, postgres-pgvector-siftly-spec.md
---

# Siftly on Vyomi — what runs today and what is still missing

**Short version:** Siftly's whole Azure data plane (Postgres + pgvector, Blob, Service Bus, Redis) now runs on Vyomi, and all four of Siftly's services run in Docker against it. What is still real-cloud is everything outside that data plane: LLMs, Azure AI Search, scrapers, email and the third-party SaaS. The database has the full schema but no data.

## 1. Siftly's architecture (for reference)

| Layer | Pieces |
| --- | --- |
| Clients | Browser (UI), customer sites (Cloudflare Worker / Vercel edge snippets), AI assistants (MCP) |
| Siftly services | `siftly-ui` (Next.js), `backend` (FastAPI, BAML LLM clients, scheduler, Service Bus workers), `backend/mcp` (read-only MCP server), `hocuspocus` (collaborative editing), `siftly-agents-2` (content engine, Mastra), `traffic-ingest-service` (publisher + worker) |
| Azure data plane | Postgres 17 + pgvector, Redis, Service Bus (5 topic/subscription pairs), Blob (2 accounts), Azure AI Search |
| External SaaS | Azure OpenAI / AI Foundry / OpenAI / Anthropic / image gen; BrightData, DataForSEO, Firecrawl; Clerk; Stripe, Lago; Resend / SES / ACS; Slack, Reddit, LinkedIn, Google OAuth / Search Console, CMS integrations; logo.dev; Sentry, PostHog |

Main pipeline: tracked prompts → AI engines (BrightData / DataForSEO) → webhook → `scrapper_responses` → scraper worker → `llm-analysis-tasks` → brand mentions, citations, rankings in Postgres → materialized views → dashboards. Content: backend → content engine → drafts + images (Blob) → Hocuspocus editing. Traffic: edge snippets → traffic-ingest → Service Bus → backend. LinkedIn drafts: `linkedin-draft-tasks`.

## 2. What Vyomi simulates for Siftly today

| Siftly dependency | Vyomi | PR | Verified |
| --- | --- | --- | --- |
| Azure Service Bus — 5 topics, peek-lock, abandon/redelivery, lock renewal, batches, async client | AMQP 1.0 listener | #43 stack, fixes in #45 | Real `azure-servicebus` 7.14.3 (sync + aio) and `@azure/service-bus` 7.9 pass; backend workers attach on Mac |
| Azure Blob — 2 accounts, 8 containers, content headers, SAS, browser GET | Blob data plane (+ Azurite) | #44 | 12/12 checks on Mac |
| Azure Cache for Redis — Lua, pipelines, pub/sub, streams | On-demand Redis | #43, fixes in #45 | 12/12 checks on Mac |
| Postgres 16 + pgvector 0.8.0 — `siftly` db/role, `vector`, `uuid-ossp`, `session_replication_role` grant | `vyomi/postgres:16-alpine-pgvector`, `vyomi db dump/restore/refresh` | #46 | Mac, PR #46 @ cfbadeb (2026-10-19): image builds (digest-pinned base), app provisions on it, Siftly's 140 tables created fresh in all 5 schemas, all 4 Siftly containers up. `verify_pg46.sh` (pgvector ops, dump/restore/refresh) not yet run |
| Connection settings for 4 services; resources from `.vyomi/app.json` | App profiles (`vyomi app`, `vyomi env`) | #43, #45 | On Mac |
| Siftly services in Docker | `docker-compose.vyomi.yml`, `./dev-vyomi.sh --docker` (Siftly branch `feat/vyomi-dev-env`) | — | backend, content engine, Hocuspocus, traffic-ingest up, 0 restarts |
| Siftly schema | `.vyomi/db/create_schema.py` (ORM models) | — | 140 of 140 tables, 5 schemas |

## 3. Still missing in Vyomi

### 3.1 Cloud services Siftly calls

| Missing | What it blocks in Siftly | Size |
| --- | --- | --- |
| **LLM gateway** — Azure OpenAI, AI Foundry (Claude, DeepSeek), OpenAI, Anthropic, image generation. Pass-through first, then record/replay | Every analysis, content and image step needs real keys, costs money and needs internet. Siftly-side prerequisite: 3 hard-coded Foundry `base_url`s in `clients.baml` must read from env | Pass-through ~1 wk; record/replay 1–2 wk |
| **Azure AI Search** — index, hybrid keyword + vector + semantic ranking | RAG and brand-facts retrieval use the real index (point `AZURE_SEARCH_INDEX_NAME` at a dev index meanwhile) | 3–6 wk |
| **Scraper replay** — BrightData, DataForSEO, Firecrawl | The visibility pipeline cannot start offline. Fixtures exist in Siftly (`backend/tests/fixtures/brightdata`, `…/dataforseo`) | ~1 wk |
| **Email** — Resend / SES / ACS into a local inbox | Outreach and notification emails; inbox polling for `outreach*@siftly.ai` | 3–5 d |
| **Webhook ingress** — a public URL into the local stack | Clerk, Stripe and BrightData callbacks (today: ngrok) | 2–3 d |
| **Edge traffic generator** — stand-in for the Cloudflare / Vercel snippets | Traffic analytics only gets hand-posted events | 1–2 d |
| **Container Apps / KEDA scaling** | Cannot test scaling under Service Bus load | Later |

### 3.2 Data

| Missing | What it blocks | Options |
| --- | --- | --- |
| **Seed / snapshot data** | Dashboards are empty | (a) Prod pull: schema dump + scoped subset, restored with `vyomi db restore --app siftly` (needs jump-VM SSH key + prod DB password). (b) Offline seed: one org + prompts, replay recorded scrapes onto `scrapper_responses`, let the real workers run, refresh views, then `vyomi db dump` (~½ d to build). (c) Synthetic SQL into metrics tables (fastest, tests least) |
| **Prod-only database objects** | `mv_url_citations_daily`, `mv_refresh_log`, `analytics.citation_refresh_work` and other views/functions created outside the ORM; the MV refresh jobs and AEO weekly sweep log errors | Come with the prod schema dump; not in the models |
| **Production-shaped pseudonymised data** (FK-aware subset) | Realistic volumes without prod access | Large, later |

### 3.3 Platform

| Missing | Why | Size |
| --- | --- | --- |
| Fault injection at the messaging-store seam | Rehearse lock loss, throttling, outages | 1–2 wk |
| `vyomi up` on Docker using the source build | `vyomi up` runs the published image from `docker-compose.cloudlite.yml`, which has no AMQP port; `dev-vyomi.sh` uses `docker-compose.yml` directly instead | S |
| Redis as a compose service (not only on-demand) | Today only via the provisioner | S |
| Blob store falls back when Azurite is configured but down | Currently stalls on retries | XS |

## 4. Not to emulate — use each provider's test mode

| Service | Used for | Local approach |
| --- | --- | --- |
| Clerk | Sign-in, orgs, webhooks | Test keys (`backend/.env`, `siftly-ui/.env.local`) + ngrok for webhooks |
| Stripe, Lago | Billing, entitlements | Stripe test mode; Lago has its own compose |
| Reddit, Slack, LinkedIn | Outreach, alerts | Test apps / keys |
| Google OAuth / Search Console | GSC metrics | Test project |
| CMS integrations | Publishing | Sandbox sites |
| logo.dev | Company logos | Real key |
| Sentry, PostHog | Errors, analytics | Off locally |

## 5. Open review findings on the PR stack

| PR | Finding | Severity |
| --- | --- | --- |
| #43 (app-env) | `vyomi env --dry-run` masks `DB_PASSWORD` but prints the password inside `DATABASE_URL` (`postgresql://siftly:<password>@…`); masking must cover secrets embedded in URL values | Security |
| #46 | ~~Fixed in cfbadeb~~ `vyomi db refresh` pass 1 refreshes `pg_matviews` in unspecified order inside one `DO` block; a view refreshed before its dependency aborts the whole refresh. Wrap each pass-1 refresh in its own exception handler | Medium |
| #46 | ~~Fixed in cfbadeb~~ Dockerfile pins pgvector version but not the `postgres:16-alpine` base digest (spec asked for a digest) | Low |
| #46 | `docker-compose.yml` publishes a fixed `5432:5432` (~~fixed in cfbadeb: `${VYOMI_POSTGRES_PORT:-5432}`~~); conflicts with any other local Postgres (`dev-vyomi.sh` warns) | Low |
| #44 | Blob store considers Azurite available when configured, without a reachability check | Low |

## 6. External inputs needed to run all of Siftly locally

| Input | Why | Source |
| --- | --- | --- |
| Docker Desktop | Runs Vyomi and Siftly | Installed |
| Vault `backend/.env` | Clerk secret, LLM keys, `INTEGRATION_ENCRYPTION_KEY`, `INTERNAL_API_KEY`, Stripe / Resend / BrightData / DataForSEO / Reddit / Slack / Firecrawl keys | Team vault |
| `siftly-ui/.env.local` | Clerk publishable key; without it the UI container is skipped | Team vault |
| Prod schema dump + data subset | Real data and prod-only views | One-time pull (jump-VM SSH key, VM IP, prod DB password) |
| `host.docker.internal` in `/etc/hosts` | Blob images load in the browser from containers' URLs | Docker Desktop setting or one `sudo` line |
| ngrok (optional) | Public URL for webhooks | ngrok account + static domain |
| Azure AI Search dev index | Avoid writing to the prod index | Vault `AZURE_SEARCH_*` |

## 7. Suggested order

1. Confirm PR #46 on the Mac (`./dev-vyomi.sh --docker`, then `verify_apps.sh`); fix the two #46 findings and the #43 masking issue.
2. Data: offline seed (or the prod pull), then `vyomi db dump` for fast resets.
3. LLM gateway — pass-through, then record/replay. Biggest cost and offline blocker.
4. Scraper replay — the visibility pipeline runs end to end offline.
5. Azure AI Search.
6. Email, webhook ingress, edge traffic generator.
7. Fault injection, scaling, production-shaped data.

## 8. How to run (Siftly branch `feat/vyomi-dev-env`)

```bash
cd ~/Downloads/generative-engine-optimization
./dev-vyomi.sh --docker 2>&1 | tee .vyomi/run.log      # Vyomi + Siftly in Docker
./.vyomi/checks/verify.sh 2>&1 | tee .vyomi/verify.log  # infra checks (real SDKs)
./.vyomi/checks/verify_apps.sh > .vyomi/apps.log 2>&1   # service checks
./dev-vyomi.sh --down                                   # stop (volumes kept)
```

Vyomi source used: `~/Documents/vyomi-siftly-build/appliance-pr46b` (PR #46 @ cfbadeb on #45 on #44).
