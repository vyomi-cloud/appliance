"""GCS object enrichments: REAL local extraction on upload (not Document AI), written to object metadata.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_enrich.py"""
import hashlib
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False
R = AwsWireRouter()
PASS = FAIL = 0
B = "enrich-bkt-1"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:400] if detail and not ok else ''}")


def call(method, path, body=None, query=None, raw=None, ctype=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    h = {"content-type": ctype} if ctype else {}
    out = R.handle(method, path, query or {}, h, data)
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], out["body"]


def upload(name, data, ctype):
    return call("POST", f"/upload/storage/v1/b/{B}/o", query={"uploadType": "media", "name": name}, raw=data, ctype=ctype)


def meta(name):
    return call("GET", f"/storage/v1/b/{B}/o/{name.replace('/', '%2F')}")[1].get("metadata", {})


def png(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


s, d = call("POST", "/storage/v1/b", {"name": B}, {"project": "p"})
check("bucket", s == 200, d)
upload("before-rule.txt", b"hello", "text/plain")
check("no rule: nothing written", "vyomi-enrich-status" not in meta("before-rule.txt"))

s, d = call("POST", f"/storage/v1/b/{B}/vyomiEnrichmentRules", {"extractors": ["metadata", "text", "image", "pdf"]}, {"ruleId": "all"})
check("rule created, labelled not Document AI", s == 200 and d["engine"] == "Vyomi local extraction (not Document AI)", d)
check("bad extractor rejected", call("POST", f"/storage/v1/b/{B}/vyomiEnrichmentRules", {"extractors": ["documentai"]}, {"ruleId": "x1"})[0] == 400)
check("duplicate rule 409", call("POST", f"/storage/v1/b/{B}/vyomiEnrichmentRules", {}, {"ruleId": "all"})[0] == 409)
check("unknown bucket 404", call("GET", "/storage/v1/b/nope-bkt/vyomiEnrichmentRules")[0] == 404)

body = b"line one\nline two has more words\n"
upload("notes.txt", body, "text/plain")
m = meta("notes.txt")
check("text: counts + sha256 written on upload", m.get("vyomi-enrich-text-lines") == "2" and m.get("vyomi-enrich-text-words") == "7"
      and m.get("vyomi-enrich-sha256") == hashlib.sha256(body).hexdigest() and m.get("vyomi-enrich-status") == "done", m)
check("labelled with engine", m.get("vyomi-enrich-engine") == "Vyomi local extraction (not Document AI)", m)
upload("data.csv", b"id,name\n1,a\n2,b\n3,c\n", "text/csv")
m = meta("data.csv")
check("csv rows + header", m.get("vyomi-enrich-text-csvRows") == "3" and m.get("vyomi-enrich-text-csvHeader") == "id,name", m)
upload("cfg.json", b'{"a": 1, "b": [1,2]}', "application/json")
check("json shape", "2 keys" in meta("cfg.json").get("vyomi-enrich-text-json", ""), meta("cfg.json"))
upload("pic.png", png(7, 5), "image/png")
m = meta("pic.png")
check("png dimensions from header", m.get("vyomi-enrich-image-width") == "7" and m.get("vyomi-enrich-image-height") == "5" and m.get("vyomi-enrich-detected-type") == "image/png", m)
pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 2>>endobj\n3 0 obj<</Type/Page>>endobj\n4 0 obj<</Type/Page>>endobj\n5 0 obj<</Title(Quarterly Report)>>endobj\n%%EOF"
upload("r.pdf", pdf, "application/pdf")
m = meta("r.pdf")
check("pdf pages + title", m.get("vyomi-enrich-pdf-pages") == "2" and m.get("vyomi-enrich-pdf-title") == "Quarterly Report", m)

# prefix filter + disable + manual run
call("DELETE", f"/storage/v1/b/{B}/vyomiEnrichmentRules/all")
call("POST", f"/storage/v1/b/{B}/vyomiEnrichmentRules", {"prefix": "inbox/", "suffix": ".txt", "extractors": ["metadata"]}, {"ruleId": "inbox"})
upload("inbox/a.txt", b"x", "text/plain")
upload("other/b.txt", b"x", "text/plain")
upload("inbox/c.png", png(1, 1), "image/png")
check("prefix+suffix rule matches only inbox/*.txt", meta("inbox/a.txt").get("vyomi-enrich-status") == "done" and "vyomi-enrich-status" not in meta("other/b.txt")
      and "vyomi-enrich-status" not in meta("inbox/c.png"))
check("metadata-only rule skips text facts", "vyomi-enrich-text-chars" not in meta("inbox/a.txt"))
s, d = call("POST", f"/storage/v1/b/{B}/vyomiEnrichmentRules/inbox:run", {"object": "inbox/a.txt"})
check("manual :run", s == 200 and d["metadata"]["vyomi-enrich-size"] == "1", d)
check("run on unmatched object 404", call("POST", f"/storage/v1/b/{B}/vyomiEnrichmentRules/inbox:run", {"object": "other/b.txt"})[0] == 404)
check("object content untouched", call("GET", f"/storage/v1/b/{B}/o/inbox%2Fa.txt", query={"alt": "media"})[1] == b"x")
s, d = call("GET", f"/storage/v1/b/{B}/vyomiEnrichmentRules")
check("rule counts processed objects", d["items"][0]["processed"] >= 2, d)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
