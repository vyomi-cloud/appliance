"""Siftly 'AI-visibility tracking' pipeline, run end-to-end against a live Vyomi appliance.

Real SDKs only: azure-servicebus (AMQP 1.0) talking to Vyomi's AMQP listener,
psycopg2 talking to Vyomi's Postgres+pgvector container. No internal test
helpers, no mocks.

Flow (mirrors Siftly's own "main pipeline" in docs/specs/siftly-on-vyomi-status.md):
  1. AI-engine scrape webhook lands  ->  Service Bus topic `scrapper_responses`
  2. scraper worker peek-locks it, extracts a brand mention, completes it,
     and hands off a task on `llm-analysis`
  3. LLM-analysis worker peek-locks that task, "scores" the mention (stubbed —
     Siftly's own status doc marks the real LLM call as still-real-cloud),
     writes the brand mention + its embedding into Postgres/pgvector, completes it,
     and — because this mention is competitive — hands off a task on `linkedin-draft`
  4. outreach worker peek-locks the linkedin-draft task to prove it's deliverable
  5. proof: pgvector ANN query (cosine distance) retrieves the row we just wrote
     by similarity, not by primary key — proving the embedding round-tripped correctly

See docs/specs/siftly-flow-demo.md for the full method, data, and result record.

Usage: python3 siftly-flow-demo.py <sas-key>
"""
import json
import sys
import time

import psycopg2
from azure.servicebus import ServiceBusClient, ServiceBusMessage, ServiceBusReceiveMode

AMQP_HOST = "localhost"
AMQP_PORT = 15672
SAS_KEY_NAME = "RootManageSharedAccessKey"
SAS_KEY = sys.argv[1] if len(sys.argv) > 1 else None
if not SAS_KEY:
    print("usage: siftly-flow-demo.py <sas-key>")
    sys.exit(1)

CONN_STR = (
    f"Endpoint=sb://{AMQP_HOST}:{AMQP_PORT};"
    f"SharedAccessKeyName={SAS_KEY_NAME};SharedAccessKey={SAS_KEY};UseDevelopmentEmulator=true;"
)

PG = dict(host="localhost", port=35432, user="postgres", password="cloudlearn", dbname="postgres")


def step(n, title):
    print(f"\n[{n}] {title}")


def recv_one(client, topic, sub, timeout=10):
    with client.get_subscription_receiver(
        topic, sub, receive_mode=ServiceBusReceiveMode.PEEK_LOCK, max_wait_time=timeout
    ) as receiver:
        msgs = receiver.receive_messages(max_message_count=1, max_wait_time=timeout)
        if not msgs:
            raise RuntimeError(f"no message arrived on {topic}/{sub} within {timeout}s")
        msg = msgs[0]
        body = b"".join(msg.body).decode() if hasattr(msg.body, "__iter__") else bytes(msg.body).decode()
        receiver.complete_message(msg)
        return json.loads(body)


def send_one(client, topic, payload):
    with client.get_topic_sender(topic) as sender:
        sender.send_messages(ServiceBusMessage(json.dumps(payload)))


def main():
    client = ServiceBusClient.from_connection_string(CONN_STR)

    # ---- Step 1: AI-engine scrape webhook -> scrapper_responses ----
    step(1, "AI-engine scrape webhook arrives -> publish to 'scrapper_responses'")
    scrape_payload = {
        "org_id": "siftly-demo-org",
        "prompt": "best AI visibility tracking tools 2026",
        "engine": "chatgpt",
        "raw_answer_excerpt": "...Siftly and Profound are leading AI visibility platforms...",
        "mentioned_brand": "Siftly",
        "citation_url": "https://siftly.ai/product",
        "scraped_at": time.time(),
    }
    send_one(client, "scrapper_responses", scrape_payload)
    print("    sent:", scrape_payload["mentioned_brand"], "citation from", scrape_payload["engine"])

    # ---- Step 2: scraper worker peek-locks it, completes, hands off to llm-analysis ----
    step(2, "scraper worker peek-lock receives it from 'scrapper_responses', completes, forwards to 'llm-analysis'")
    scraped = recv_one(client, "scrapper_responses", "scrapper_responses")
    print("    received + completed:", scraped["prompt"])
    analysis_task = {
        "org_id": scraped["org_id"],
        "mentioned_brand": scraped["mentioned_brand"],
        "citation_url": scraped["citation_url"],
        "excerpt": scraped["raw_answer_excerpt"],
    }
    send_one(client, "llm-analysis", analysis_task)

    # ---- Step 3: LLM-analysis worker peek-locks it, scores it, writes to Postgres/pgvector ----
    step(3, "LLM-analysis worker peek-lock receives 'llm-analysis' task, scores it, writes brand mention + embedding to Postgres/pgvector")
    task = recv_one(client, "llm-analysis", "llm-analysis")
    print("    received + completed:", task["mentioned_brand"], task["citation_url"])

    # Stand-in for the real LLM scoring call (Siftly's own status doc marks the
    # actual model call as still-real-cloud/out of Vyomi's scope). Sentiment
    # score + a toy embedding derived deterministically from the text so the
    # pgvector ANN proof step below is reproducible.
    sentiment = 0.87
    embedding = [((hash(task["excerpt"] + str(i)) % 2000) - 1000) / 1000.0 for i in range(8)]
    embedding_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS siftly_demo_brand_mentions (
            id SERIAL PRIMARY KEY,
            org_id TEXT NOT NULL,
            brand TEXT NOT NULL,
            citation_url TEXT NOT NULL,
            sentiment REAL NOT NULL,
            embedding VECTOR(8) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        """
    )
    cur.execute(
        "INSERT INTO siftly_demo_brand_mentions (org_id, brand, citation_url, sentiment, embedding) "
        "VALUES (%s, %s, %s, %s, %s::vector) RETURNING id;",
        (task["org_id"], task["mentioned_brand"], task["citation_url"], sentiment, embedding_literal),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    print(f"    wrote row id={row_id} sentiment={sentiment} embedding={[round(x,3) for x in embedding]}")

    is_competitive = task["mentioned_brand"].lower() == "siftly" and sentiment > 0.5
    if is_competitive:
        send_one(client, "linkedin-draft", {
            "org_id": task["org_id"],
            "reason": "positive brand mention worth amplifying",
            "citation_url": task["citation_url"],
        })

    # ---- Step 4: outreach worker peek-locks the linkedin-draft task ----
    step(4, "outreach worker peek-lock receives the follow-up task from 'linkedin-draft'")
    draft_task = recv_one(client, "linkedin-draft", "linkedin-draft")
    print("    received + completed draft task:", draft_task["reason"])

    # ---- Step 5: proof — pgvector ANN query retrieves the row by similarity, not by id ----
    step(5, "proof: pgvector cosine-distance ANN query retrieves the row by similarity")
    cur.execute(
        "SELECT id, brand, citation_url, 1 - (embedding <=> %s::vector) AS cosine_similarity "
        "FROM siftly_demo_brand_mentions ORDER BY embedding <=> %s::vector LIMIT 1;",
        (embedding_literal, embedding_literal),
    )
    top = cur.fetchone()
    assert top[0] == row_id, f"ANN search did not retrieve the row we just wrote: {top}"
    print(f"    ANN top match: id={top[0]} brand={top[1]} citation_url={top[2]} cosine_similarity={top[3]:.6f}")

    cur.close()
    conn.close()
    print("\nFLOW OK: scrapper_responses -> llm-analysis -> Postgres/pgvector -> linkedin-draft, all over real SDKs against Vyomi.")


if __name__ == "__main__":
    main()
