# Chapter 7: Agent Memory

_Short-term session memory and retrievable long-term facts_

**What you build:** Give the agent memory: short-term events inside a session and long-term facts it can retrieve later.

## Code, in order

### 1. Install the libraries

Chapter 9 gives the agent memory. Azure splits it honestly in two. SHORT-TERM memory (the events of one session) is a managed feature: an Assistants / Foundry *thread* stores the messages and their metadata. LONG-TERM memory (facts that outlive a session) is NOT a managed Azure service: Azure has no counterpart to AgentCore Memory or Vertex AI Memory Bank, so you build it yourself as an application pattern on Azure Table storage, and this chapter says so in the code. It uses `azlab.py` and `azdata.py` (chapters 10 and 7).

- File: [`app/install9.sh`](../app/install9.sh)

### 2. Short-term memory: a thread

Create a thread with metadata (who and which session), add two user messages, read them back in order, update the metadata, then run an assistant on the thread: the run reads the whole thread and appends its reply to it. The thread is the session's memory: the service keeps the messages for you. Be clear about what this block proves: the model here is the repo's deterministic test stub, which only echoes the last user message, so it verifies the mechanics (history in order, metadata, a run that completes and appends to the same thread), not that a model recalls the badge number. A larger model would answer '4412' to a question about the badge.

- File: [`app/short_term.py`](../app/short_term.py)
- Run: `cd app && python short_term.py`
- You should see: `thread now holds 3 messages (2 user + 1 assistant)`

### 3. Long-term memory: write the helper

Facts are rows in a Table called `longtermmemory`. `PartitionKey` is `tenant|user`, so one user can only ever read their own rows and a tenant boundary is part of every key: that is the scoping rule for memory (never trust a fact from another user, and never let one user's text become another's context). Each row keeps its source and a timestamp so you can expire or audit it. `remember` upserts, `recall` reads, `forget` deletes (retention and right to erasure).

- File: [`app/memory.py`](../app/memory.py)

### 4. Try it: a new session recalls a fact, another user cannot

Session one stores a preference. A completely new process (a new session, a new thread) reads it back. A second user sees nothing. Then `forget` removes it.

- File: [`app/try_memory.py`](../app/try_memory.py)
- Run: `cd app && python try_memory.py`
- You should see: `new session recalls: prefers floor 3 east wing for inspections`

### 5. Confirm there is no managed long-term memory API

A check, not a feature: the Azure OpenAI / Foundry surface has no memory-store route. Both probes must answer 404 or 405. This is why the previous two blocks are your own code and not an Azure service.

- File: [`app/no_managed_memory.py`](../app/no_managed_memory.py)
- Run: `cd app && python no_managed_memory.py`
- You should see: `no managed long-term memory API`

## It works when

- thread history in order
- a fact is recalled in a new session
