"""Cover /api/runtime/{audit-sinks,notification-channels}[/{id}[/test]] and the read-only runtime
health routes. Tier-locked features must answer 403 tier_feature_locked, never a 5xx."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def locked(r):
    if r.status_code != 403:
        return False
    d = r.json().get("detail") or {}
    return isinstance(d, dict) and str(d.get("code", "")).startswith("tier_feature")


def crud(kind, listkey, payload):
    url = f"{BASE}/api/runtime/{kind}"
    r = requests.get(url, timeout=30)
    if locked(r):
        check(f"{kind} list is tier-locked with a 403 (not 5xx)", True)
        for m, u in (("post", url), ("delete", url + "/nope")):
            check(f"{kind} {m} locked 403", locked(getattr(requests, m)(u, json=payload, timeout=30)))
        return
    check(f"{kind} list 200", r.status_code == 200 and isinstance(r.json().get(listkey), list))
    r = requests.post(url, json=payload, timeout=30)
    check(f"{kind} register 200 (got {r.status_code})", r.status_code == 200)
    item = r.json() if r.status_code == 200 else {}
    iid = item.get("id") or item.get("sink_id") or item.get("channel_id")
    check(f"{kind} register returns an id", bool(iid))
    if iid:
        ids = [x.get("id") for x in requests.get(url, timeout=30).json().get(listkey, [])]
        check(f"{kind} registered item is listed", iid in ids)
        if kind == "notification-channels":
            r = requests.post(f"{url}/{iid}/test", timeout=30)
            check(f"{kind} test is not a 5xx (got {r.status_code})", r.status_code < 500)
        r = requests.delete(f"{url}/{iid}", timeout=30)
        check(f"{kind} delete 200", r.status_code == 200 and r.json().get("deleted") == iid)
        ids = [x.get("id") for x in requests.get(url, timeout=30).json().get(listkey, [])]
        check(f"{kind} deleted item is gone", iid not in ids)
    r = requests.delete(f"{url}/does-not-exist", timeout=30)
    check(f"{kind} delete unknown is 404", r.status_code == 404)


def main():
    crud("audit-sinks", "sinks", {"kind": "webhook", "url": "http://127.0.0.1:9/sink", "name": "conf"})
    crud("notification-channels", "channels",
         {"kind": "webhook", "url": "http://127.0.0.1:9/hook", "name": "conf", "events": []})
    for p in ("disk-health", "disk-cleanup/suggestions", "service-metrics", "host-distribution"):
        r = requests.get(f"{BASE}/api/runtime/{p}", timeout=60)
        ok = r.status_code == 200 and isinstance(r.json(), (dict, list))
        check(f"runtime/{p} answers JSON, no 5xx (got {r.status_code})", ok or locked(r))
    sys.exit(1 if failed else 0)


main()
