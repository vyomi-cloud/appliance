"""Nano: the IAM resource page GETs /api/iam/users|roles|groups/<name>, and an unsaved
detail-tab settings record answers 200 (defaults), not 404. Pure Python, no browser."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wasm.backends.store import Backends
from wasm import providers as P

failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


b = Backends()
P.dispatch(b, "aws", "iam", "CreateUser", params={"name": "new-user"})
r = P.dispatch(b, "aws", "iam", "GetUser", params={"name": "new-user"})
check("GetUser returns the created user", r.get("ok") and r.get("user_name") == "new-user" and r.get("arn"), r)
check("GetUser has user_id + created", bool(r.get("user_id")) and bool(r.get("created")), r)
r = P.dispatch(b, "aws", "iam", "GetUser", params={"name": "nobody"})
check("GetUser unknown -> NoSuchEntity", r.get("ok") is False and r.get("code") == "NoSuchEntity", r)
r = P.dispatch(b, "aws", "iam", "GetRole", params={"name": "nobody"})
check("GetRole unknown -> NoSuchEntity", r.get("ok") is False and r.get("code") == "NoSuchEntity", r)
r = P.dispatch(b, "aws", "iam", "GetGroup", params={"name": "nobody"})
check("GetGroup unknown -> NoSuchEntity", r.get("ok") is False and r.get("code") == "NoSuchEntity", r)
r = P.dispatch(b, "aws", "_resource", "Get", params={"service": "iam~new-user~passwordPolicy", "name": "_settings"})
check("unsaved _settings -> ok empty record", r.get("ok") is True, r)
P.dispatch(b, "aws", "_resource", "Create", params={"service": "iam~new-user~passwordPolicy",
           "body": {"name": "_settings", "minimum_length": 12}})
r = P.dispatch(b, "aws", "_resource", "Get", params={"service": "iam~new-user~passwordPolicy", "name": "_settings"})
check("saved _settings round-trips", r.get("ok") and r.get("minimum_length") == 12, r)
r = P.dispatch(b, "aws", "_resource", "Get", params={"service": "iam~x~y", "name": "other"})
check("missing non-settings record still NotFound", r.get("ok") is False, r)
sys.exit(1 if failed else 0)
