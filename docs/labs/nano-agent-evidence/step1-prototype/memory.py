"""Memory in DynamoDB. Two kinds: conversation notes (what was said in this session) and long-term notes (facts about the user that outlive it).
The runtime, not the model, decides what to store: small models do not manage their own memory reliably."""
import re
import time

from aws import ddb
from data import MEMORY

REMEMBER = re.compile(r"\bremember\b(?: that)?\s+(.+)", re.I)


def _query(pk, prefix, forward=True, limit=None):
    kw = dict(TableName=MEMORY, KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
              ExpressionAttributeValues={":p": {"S": pk}, ":s": {"S": prefix}}, ScanIndexForward=forward)
    if limit:
        kw["Limit"] = limit
    return [{k: v["S"] for k, v in it.items()} for it in ddb.query(**kw).get("Items", [])]


def load_context(session_id, user_id):
    """The text put in front of the model: what we know about the user, and the last few exchanges of this session."""
    notes = [n["text"] for n in _query("user#" + user_id, "note#")][-5:]
    turns = _query("session#" + session_id, "turn#")
    lines = []
    if notes:
        lines.append("Known about this user: " + " | ".join(notes))
    for t in turns[-3:]:
        lines.append("Earlier: user asked '%s' and you replied '%s'" % (t["q"][:120], t["a"][:160]))
    return "\n".join(lines), len(turns)


def save_turn(session_id, n, question, answer):
    ddb.put_item(TableName=MEMORY, Item={"pk": {"S": "session#" + session_id}, "sk": {"S": "turn#%05d" % (n + 1)},
                                         "q": {"S": question[:300]}, "a": {"S": answer[:300]}})


def remember(user_id, question):
    """'Remember that my usual asset is AHU-7' -> a long-term note. Returns the note, or None when the message is not a request to remember."""
    m = REMEMBER.search(question)
    if not m:
        return None
    note = m.group(1).strip().rstrip(".!")[:200]
    n = len(_query("user#" + user_id, "note#")) + 1
    ddb.put_item(TableName=MEMORY, Item={"pk": {"S": "user#" + user_id}, "sk": {"S": "note#%03d" % n}, "text": {"S": note}})
    return note
