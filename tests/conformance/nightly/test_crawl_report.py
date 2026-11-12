"""crawl_report.py: findings become AUTO rows; repeats update; a fixed finding on a crawled service resolves; uncrawled services never resolve.
Run: python3 tests/conformance/nightly/test_crawl_report.py"""
import importlib.util, json, shutil, tempfile
from pathlib import Path
H = Path(__file__).parent
spec = importlib.util.spec_from_file_location("cr", H / "crawl_report.py"); cr = importlib.util.module_from_spec(spec); spec.loader.exec_module(cr)
ki = cr.ki
d = Path(tempfile.mkdtemp()); md = d / "KI.md"; shutil.copy(ki.DEFAULT, md)


def ui(name, services):
    p = d / name; p.write_text(json.dumps({"target": "nano", "services": services})); return [str(p)]


def check(n, c):
    if not c: raise AssertionError(n)
    print("  ok ", n)


svc = lambda cloud, s, f: {"cloud": cloud, "service": s, "findings": [{"type": t, "detail": dt} for t, dt in f]}
r = cr.report("azure", ui("a.json", [svc("azure", "Event Grid system topics", [("PLACEHOLDER_CELL", "Topic type shows -"), ("HTTP_5XX", "x -> 503")]),
                                       svc("azure", "Storage accounts", [])]), md)
check("two findings added", len(r["added"]) == 2 and r["crawled"] == 2)
ids = {x["id"]: x for x in ki.list_open("azure", md)}
check("5xx is S2, placeholder cell is S3", ids["AUTO-azure-crawl-event-grid-system-topics-http-5xx"]["impact"] == "S2"
      and ids["AUTO-azure-crawl-event-grid-system-topics-placeholder-cell"]["impact"] == "S3")
r = cr.report("azure", ui("b.json", [svc("azure", "Event Grid system topics", [("PLACEHOLDER_CELL", "Topic type shows -"), ("HTTP_5XX", "x -> 503")])]), md)
check("repeat run updates, no duplicates", not r["added"] and len(r["updated"]) == 2
      and len([i for i in ki.list_open("azure", md) if i["id"].startswith("AUTO-azure-crawl")]) == 2)
r = cr.report("azure", ui("c.json", [svc("azure", "Event Grid system topics", [("PLACEHOLDER_CELL", "Topic type shows -")])]), md)
check("a finding that disappeared on a crawled service resolves", r["resolved"] == ["AUTO-azure-crawl-event-grid-system-topics-http-5xx"])
r = cr.report("azure", ui("d.json", [svc("azure", "Resource groups", [])]), md)
check("a service that was NOT crawled keeps its row", not r["resolved"]
      and any(i["id"].endswith("placeholder-cell") for i in ki.list_open("azure", md)))
r = cr.report("aws", ui("e.json", [svc("azure", "Event Grid system topics", [("HTTP_5XX", "zzz")])]), md)
check("other clouds' findings are ignored", r["crawled"] == 0 and not r["added"])
r = cr.report("gcp", ui("f.json", [svc("gcp", "Compute Engine", [("PAGE_ERROR", "boom")])]), md)
check("gcp works the same", r["added"] == ["AUTO-gcp-crawl-compute-engine-page-error"])
print("PASS")
