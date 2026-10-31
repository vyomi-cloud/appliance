---
title: Siftly main pipeline — one flow run end-to-end against Vyomi
status: demo record (verification artifact, not a feature change)
updated: 2026-10-31
owner: Rohith
related:
  - PR #34→#45 "Azure Service Bus over AMQP 1.0" (backend-upgrade issue #181, rebuilt as PR #188)
  - PR #43, #44, #46 "Siftly: app profiles, Blob fidelity, Postgres+pgvector" (backend-upgrade issue #182, rebuilt as PR #194)
  - docs/specs/siftly-on-vyomi-status.md
  - docs/specs/siftly-flow-demo.py (the exact script run for this demo)
---

# Siftly main pipeline — one flow run end-to-end against Vyomi

## 1. What this is

A record of a single, concrete run of Siftly's "AI-visibility tracking" main
pipeline against a **live Vyomi appliance**, using only real third-party SDKs
(no Vyomi-internal test helpers), to demonstrate that Vyomi's Service Bus
(AMQP 1.0) and Postgres+pgvector emulation can actually carry one of Siftly's
real flows.

This branch (`demo/siftly-flow`) is the combination used to run the demo: PR
#188's rebuild of the Service Bus/AMQP stack (#34→#45) merged with PR #194's
rebuild of the app-profile/Blob/Postgres stack (#43/#44/#46) — both already
"ready" per `tests/conformance/expansion/upgrades/*.json` on their own
branches. It is pushed here **for reference only**: to let the Service Bus
AMQP stack and the Postgres/pgvector stack be exercised together and to keep
a record of how/what was tested. It is not a PR and is not meant to be merged
as-is — #188 and #194 are the real review/merge path for this code.

## 2. Background: what Siftly is and what Vyomi emulates for it

Siftly is a GEO ("Generative Engine Optimization") SaaS: it tracks how AI
engines (ChatGPT, etc.) cite a brand in response to tracked prompts, scores
those mentions with an LLM, stores the results, and can draft LinkedIn
outreach off the back of them.

Per `docs/specs/siftly-on-vyomi-status.md`, Siftly's Azure data plane is:

| Azure service | Vyomi emulation | Source PRs |
| --- | --- | --- |
| Service Bus — 5 topic/subscription pairs, peek-lock, abandon/redelivery, lock renewal, batches | AMQP 1.0 listener (`core/servicebus_amqp/`) | #34→#40, #45 |
| Postgres 16 + pgvector 0.8.0 | `vyomi/postgres:16-alpine-pgvector` image | #46 |
| Blob (2 accounts, 8 containers) | Blob data plane + Azurite | #44 |
| Redis | On-demand Redis | #43, #45 |

Siftly's canonical 5 Service Bus topics (`core/azure_servicebus_runtime.py`,
`SIFTLY_TOPICS`): `scrapper_responses`, `partner-scraper-responses`,
`llm-analysis`, `linkedin-draft`, `traffic-ingest`. Each gets a same-named
subscription, bootstrapped automatically on first store access.

Siftly's own stated main pipeline:
> tracked prompts → AI engines (BrightData/DataForSEO) → webhook →
> `scrapper_responses` → scraper worker → `llm-analysis-tasks` → brand
> mentions/citations/rankings in Postgres → materialized views → dashboards.
> … LinkedIn drafts: `linkedin-draft-tasks`.

This demo runs one instance of exactly that pipeline, end to end.

**Scope note:** PRs #34-45, #43/44/46, and their rebuilds #188/#194 were all
still open and unmerged to `main` as of this writing. This branch is a local
combination of the two rebuilds, used only to get one appliance running both
stacks at once — nothing in #188 or #194 was modified.

## 3. Method

### 3.1 Getting a combined build

```bash
# Scratch worktree off the already-"ready" Service Bus rebuild (PR #188)
git worktree add /tmp/vyomi/wt/siftly -b demo/siftly-flow origin/expansion/upgrade-servicebus-amqp
cd /tmp/vyomi/wt/siftly

# Merge in the already-"ready" Blob/Postgres/app-profile rebuild (PR #194)
git merge origin/expansion/upgrade-siftly-runtime --no-edit
# -> one conflict, in .gitignore (both branches added new ignore lines);
#    resolved by keeping both sides' lines, nothing else conflicted.
```

Neither #188 nor #194 was modified, force-pushed, or had its history
rewritten — this branch only adds a merge commit on top, plus this write-up.

### 3.2 Bringing up Vyomi

```bash
docker compose build simulator vyomi-sql-postgres

# The repo's own docker-compose.override.yml remaps most backend ports to
# avoid clashing with a developer's local services, and in doing so drops
# the simulator's AMQP port mappings entirely. A small local-only override
# (docker-compose.demo.yml, not committed — host ports only, no code change)
# restored them for the duration of the demo:
#   simulator:
#     ports:
#       - "${VYOMI_SIMULATOR_PORT:-9200}:9000"
#       - "15672:5672"   # AMQP
#       - "15671:5671"   # AMQPS

docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.demo.yml up -d simulator vyomi-sql-postgres vyomi-gcs
```

Resulting local endpoints:
- Vyomi REST console: `http://localhost:9200`
- Vyomi AMQP 1.0 (Service Bus): `localhost:15672`
- Postgres 16 + pgvector: `localhost:35432` (user `postgres` / password `cloudlearn`)

Verified before testing:
```bash
curl -s http://localhost:9200/healthz
# {"status":"ok","tier":"free","packs_active":0}

docker compose exec simulator cat /data/.vyomi_servicebus_sas_key
# this install's per-boot generated SAS key (core/servicebus_amqp/lifecycle.py,
# get_or_create_sas_key() — same persist-to-disk pattern as the admin key)
```

The Service Bus connection string used by the test client (same format
`core/servicebus_amqp/lifecycle.py:get_connection_string()` generates, pointed
at the host-mapped AMQP port instead of the container-internal one):
```
Endpoint=sb://localhost:15672;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=<key from above>;UseDevelopmentEmulator=true;
```

### 3.3 Test client

A Python virtualenv with **only real, third-party SDKs** — no Vyomi test
helpers:

```bash
python3 -m venv .venv
./.venv/bin/pip install azure-servicebus psycopg2-binary
# azure-servicebus 7.15.0, psycopg2-binary 2.9.x
```

Confirmed the Postgres backend's identity directly before running the flow:
```sql
SELECT version();   -- PostgreSQL 16.15 on aarch64-unknown-linux-musl …
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname='vector';  -- 0.8.0
```

### 3.4 The flow script

`docs/specs/siftly-flow-demo.py` (checked into this branch alongside this
doc), run once against the live appliance, playing the role of each Siftly
worker in turn:

```bash
./.venv/bin/python docs/specs/siftly-flow-demo.py <sas-key-from-3.2>
```

1. **Publish** a scrape-webhook message to Service Bus topic `scrapper_responses`
   (`ServiceBusClient.get_topic_sender(...).send_messages(...)`).
2. **Scraper worker**: peek-lock receive from `scrapper_responses`/`scrapper_responses`,
   complete it, then publish a derived task to `llm-analysis`.
3. **LLM-analysis worker**: peek-lock receive from `llm-analysis`/`llm-analysis`,
   score it and compute an embedding, write both to Postgres/pgvector,
   complete the message, then — because the mention is positive — publish a
   task to `linkedin-draft`.
4. **Outreach worker**: peek-lock receive from `linkedin-draft`/`linkedin-draft`,
   complete it.
5. **Proof query**: pgvector cosine-distance (`<=>`) `ORDER BY` query against
   the row just written, asserting it comes back as the nearest neighbour to
   its own embedding (i.e. retrieved by similarity, not by primary key).

All Service Bus traffic goes over AMQP 1.0 through the real `azure-servicebus`
SDK; all Postgres traffic goes through `psycopg2` with the real `vector` type
cast (`%s::vector`).

### 3.5 Post-run verification

A second, independent check (not part of the flow script) that every topic's
backlog is actually empty — i.e. messages were genuinely **completed**
(Accepted disposition, removed from the store), not just left to time out:

```python
for topic in ("scrapper_responses", "llm-analysis", "linkedin-draft"):
    with client.get_subscription_receiver(
        topic, topic, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE, max_wait_time=2
    ) as r:
        leftover = r.receive_messages(max_message_count=10, max_wait_time=2)
    print(f"{topic}: {len(leftover)} messages left in backlog after the flow")
```

## 4. Data used

All data is synthetic, generated by the script itself — nothing pulled from
real Siftly traffic or a real LLM:

| Field | Value used | Represents |
| --- | --- | --- |
| `org_id` | `siftly-demo-org` | tenant owning the tracked prompt |
| `prompt` | `"best AI visibility tracking tools 2026"` | the tracked prompt Siftly polls AI engines with |
| `engine` | `"chatgpt"` | which AI answer engine produced the citation |
| `raw_answer_excerpt` | `"...Siftly and Profound are leading AI visibility platforms..."` | the scraped answer text |
| `mentioned_brand` | `"Siftly"` | brand extracted from the excerpt |
| `citation_url` | `"https://siftly.ai/product"` | citation source URL |
| `sentiment` | `0.87` (hardcoded) | stand-in for a real LLM sentiment score |
| `embedding` | 8-dim vector, `((hash(excerpt + i) % 2000) - 1000) / 1000.0` for `i in range(8)` | stand-in for a real embedding model call — deterministic from the excerpt text so the pgvector ANN proof step is reproducible |

The real LLM scoring/embedding call was **intentionally stubbed**, not
emulated: Siftly's own status doc lists the LLM gateway (Azure OpenAI/AI
Foundry/OpenAI/Anthropic) as still-real-cloud and out of Vyomi's scope — this
demo only needed *some* embedding to prove the pgvector round-trip, not a
semantically meaningful one.

The Postgres table created for this demo (not part of Siftly's real 140-table
ORM schema, which lives in Siftly's own private repo and wasn't available
here):

```sql
CREATE TABLE siftly_demo_brand_mentions (
    id SERIAL PRIMARY KEY,
    org_id TEXT NOT NULL,
    brand TEXT NOT NULL,
    citation_url TEXT NOT NULL,
    sentiment REAL NOT NULL,
    embedding VECTOR(8) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

## 5. Result (actual output)

```
[1] AI-engine scrape webhook arrives -> publish to 'scrapper_responses'
    sent: Siftly citation from chatgpt

[2] scraper worker peek-lock receives it from 'scrapper_responses', completes, forwards to 'llm-analysis'
    received + completed: best AI visibility tracking tools 2026

[3] LLM-analysis worker peek-lock receives 'llm-analysis' task, scores it, writes brand mention + embedding to Postgres/pgvector
    received + completed: Siftly https://siftly.ai/product
    wrote row id=1 sentiment=0.87 embedding=[-0.057, -0.768, 0.007, -0.325, -0.711, -0.841, -0.918, 0.906]

[4] outreach worker peek-lock receives the follow-up task from 'linkedin-draft'
    received + completed draft task: positive brand mention worth amplifying

[5] proof: pgvector cosine-distance ANN query retrieves the row by similarity
    ANN top match: id=1 brand=Siftly citation_url=https://siftly.ai/product cosine_similarity=1.000000

FLOW OK: scrapper_responses -> llm-analysis -> Postgres/pgvector -> linkedin-draft, all over real SDKs against Vyomi.
```

Independent backlog check, run after the script exited:
```
scrapper_responses: 0 messages left in backlog after the flow
llm-analysis: 0 messages left in backlog after the flow
linkedin-draft: 0 messages left in backlog after the flow
```

## 6. What this proves, and what it doesn't

**Proves:**
- Vyomi's AMQP 1.0 listener correctly carries a real `azure-servicebus`
  client through send → peek-lock receive → complete, three times in a row,
  across three different topic/subscription pairs, with each completion
  genuinely settling the message (confirmed by the empty-backlog check, not
  just inferred from no exception being raised).
- Vyomi's Postgres+pgvector backend accepts a real `vector` column write and
  answers a cosine-distance ANN query correctly (the inserted row is returned
  as its own nearest neighbour).
- One of Siftly's real pipeline shapes (scrape → scraper worker → LLM task →
  Postgres write → outreach task → outreach worker) can run unmodified against
  Vyomi, using only the SDKs Siftly itself would use.

**Does not prove:**
- Siftly's actual application code runs against Vyomi — that code (Next.js
  UI, FastAPI backend, BAML LLM clients, content engine, Hocuspocus,
  traffic-ingest-service) lives in Siftly's own private repo
  (`generative-engine-optimization`), which wasn't available here. This demo
  played each worker's role by hand with equivalent SDK calls.
- Blob storage or the `traffic-ingest` / `partner-scraper-responses` topics
  work — only 3 of Siftly's 5 topics and none of Blob were exercised.
- The full 140-table Siftly ORM schema provisions correctly — that's an
  app-profile step (`vyomi app` / `vyomi env` / `.vyomi/db/create_schema.py`)
  owned by Siftly's own repo; this demo used one ad hoc table instead.
- Anything about real LLM scoring or embedding quality — both were stubbed
  deterministically, by design.
- That PRs #34-45 / #43/44/46, or their rebuilds #188/#194, are mergeable or
  safe to merge as-is — this demo only exercised runtime behavior, not CI,
  review, or merge-readiness.

## 7. Cleanup

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.demo.yml down   # containers removed, volumes kept
```
