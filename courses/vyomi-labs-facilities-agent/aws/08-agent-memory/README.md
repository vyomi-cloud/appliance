# Layer 8: Agent Memory

_Short-term session memory and retrievable long-term facts_

**What you build:** Give the agent memory: short-term events inside a session and long-term facts it can retrieve later.

## Code, in order

### 1. Create the memory

An AgentCore Memory holds short-term events (the raw turns of a conversation) and, through a strategy, long-term records the agent can recall in later sessions. The semantic strategy extracts durable facts. Events expire after 30 days.

- File: [`memory_create.py`](./memory_create.py)
- Run: `python memory_create.py` (or `./run_all.sh 8` from the project root)
- You should see: `memory `

### 2. Write and replay a conversation

CreateEvent appends one turn to a session of an actor (a user). ListEvents replays the session, which is how the agent resumes a conversation. The two turns here are the real question and a short answer.

- File: [`memory_events.py`](./memory_events.py)
- Run: `python memory_events.py` (or `./run_all.sh 8` from the project root)
- You should see: `replayed 2 events`

### 3. Recall long-term records

RetrieveMemoryRecords searches what the memory strategy extracted for this actor. Extraction runs in the background on real AWS, so a fresh memory may legitimately return zero records for a while.

- File: [`memory_recall.py`](./memory_recall.py)
- Run: `python memory_recall.py` (or `./run_all.sh 8` from the project root)
- You should see: `long-term records for maria:`

## It works when

- facilities-memory exists
- events round-trip
- memory records are retrievable
