"""Share-feedback endpoint (offline appliance): stores a note, rejects empty, limits abuse."""
import json, os, sys, tempfile
os.environ["CLOUDLEARN_STATE_DIR"] = tempfile.mkdtemp(prefix="feedback-")
from core import feedback as F
bad = 0
def check(n, ok, d=""):
    global bad; bad += 0 if ok else 1; print(("PASS " if ok else "FAIL ") + n + ("" if ok else " " + str(d)))
r = F.record({"text": "  nice console  ", "cloud": "aws", "substrate": "nano", "evil": "x"})
check("stores trimmed text + whitelisted fields", r["text"] == "nice console" and r["cloud"] == "aws" and "evil" not in r, r)
check("text truncated to 2000", len(F.record({"text": "a" * 5000})["text"]) == 2000)
try: F.record({"text": "   "}); check("empty rejected", False)
except ValueError: check("empty rejected", True)
lines = open(F._path()).read().strip().splitlines()
check("jsonl appended", len(lines) == 2 and json.loads(lines[0])["text"] == "nice console", lines)
from fastapi import FastAPI
from fastapi.testclient import TestClient
a = FastAPI(); F.register(a); c = TestClient(a)
check("POST ok", c.post("/api/feedback", json={"text": "hi"}).json() == {"ok": True})
check("POST empty -> 400", c.post("/api/feedback", json={"text": ""}).status_code == 400)
codes = [c.post("/api/feedback", json={"text": "x"}).status_code for _ in range(12)]
check("rate limited after 10", 429 in codes, codes)
print("FAILS", bad); sys.exit(1 if bad else 0)
