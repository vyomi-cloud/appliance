# Chapter 4: Memory

_An agent that remembers what you said in the session and what you asked it to keep_

**What you build:** Give the agent two kinds of memory in DynamoDB: notes about the conversation and long-term notes about the user.

## Code, in order

### 1. Write the memory module

load_context reads the user's notes and the last exchanges; save_turn writes a conversation note; remember turns a remember request into a long-term note.

- File: [`memory.py`](./memory.py)

### 2. Add memory to the agent

The same loop. Before the first model call it loads context; after the turn it saves a note. A message that starts remember is handled with no model call.

- File: [`agent.py`](./agent.py)

### 3. Test both memories

Tell the agent a fact, use it in another session, check it is scoped to the user, and check the session notes. This step needs a model.

- File: [`try_memory.py`](./try_memory.py)
- Run: `python try_memory.py`
- You should see: `memory ok`

## It works when

- a remember request is stored without a model call
- the note is visible in a new session for the same user
- another user does not see it
- the agent uses the note to answer
- the session keeps its conversation notes
