"""Memory in two scopes. A session note survives inside one conversation; a long-term note survives across conversations."""
import agent
import seed
from aws import ddb
from data import MEMORY
from memory import load_context

seed.seed()

# 1. Long-term: tell the agent a fact in one session, use it in another. No model is needed to store it.
r = agent.run_turn("Please remember that my usual asset is AHU-7.", session_id="ch4-s1", user_id="ch4-priya")
assert r["type"] == "answer" and r["model_calls"] == 0 and "AHU-7" in r["text"], r
ctx, n = load_context("ch4-s2", "ch4-priya")
assert "my usual asset is AHU-7" in ctx and n == 0, ctx
print("long-term note stored and visible in a new session:", ctx)

# 2. The stored note is real DynamoDB data, scoped to the user.
items = ddb.query(TableName=MEMORY, KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": {"S": "user#ch4-priya"}})["Items"]
assert len(items) == 1
other, _ = load_context("ch4-s3", "ch4-someone-else")
assert "AHU-7" not in other, "one user's note must not reach another user"
print("scoped to the user: another user sees nothing")

# 3. Use it: a new session, a question that only makes sense with the note.
r = agent.run_turn("What is the status of my usual asset?", session_id="ch4-s2", user_id="ch4-priya")
print("steps:", [s["action"] for s in r["steps"]])
print("reply:", r["text"])
assert r["type"] == "answer" and "degraded" in r["text"].lower(), r

# 4. Short-term: the session remembers what was said.
ctx, n = load_context("ch4-s2", "ch4-priya")
assert n == 2 and "status of my usual asset" in ctx, (n, ctx)
print("conversation notes in this session:", n)
print("memory ok")
