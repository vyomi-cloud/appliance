# Chapter 7: Agent Memory

_Short-term session memory and retrievable long-term facts_

**What you build:** Give the agent memory: short-term events inside a session and long-term facts it can retrieve later.

## Code, in order

### 1. Install the libraries

Chapter 9 gives the agent memory with Vertex AI Agent Platform Sessions (short-term: the events of one conversation) and Memory Bank (long-term: facts that outlive a session). It relies on gcp.py (chapter 10) and the agents.py supervisor from chapter 3.

- File: [`app/install_9.sh`](../app/install_9.sh)

### 2. Create the memory host

Sessions and Memory Bank hang off an Agent Engine resource. This creates a small one named facilities_memory purely to host them (it runs no code of its own), and a helper that finds it again by name.

- File: [`app/memory.py`](../app/memory.py)
- Run: `cd app && python memory.py`
- You should see: `memory host: projects/`

### 3. Keep a conversation in a session

Short-term memory is the ordered list of events in one session. Create a session for the user maria, run the supervisor from chapter 3 on a question, append the user turn and the agent turn as events, then read the session back, which is what a replay or an audit does. Each user gets their own session.

- File: [`app/session_demo.py`](../app/session_demo.py)
- Run: `cd app && python session_demo.py`
- You should see: `events replayed: 2`

### 4. Remember a long-term fact

Memory Bank stores facts scoped to a user and retrieves them by similarity, so a later session can recall what an earlier one learned. Create a fact for maria and retrieve it with a related query.

- File: [`app/remember.py`](../app/remember.py)
- Run: `cd app && python remember.py`
- You should see: `another user's memories: 0`

### 5. Let the model extract facts from a conversation

Instead of writing facts by hand, ask Memory Bank to generate them from a conversation. This step uses the model; in this verification that is the deterministic test stub, so the call is proven to work but the facts it extracts are not what a larger model would extract.

- File: [`app/generate_memories.py`](../app/generate_memories.py)
- Run: `cd app && python generate_memories.py`
- You should see: `memories generated from the conversation`

## It works when

- engine exists
- session events round-trip
- fact retrievable by similarity
