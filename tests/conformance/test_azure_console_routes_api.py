"""Azure console routes without a prior literal-path test: summary, NSG reconcile, Azure VM
console/connect (/api/azure/vm/*, /api/console/azurevm/*), Azure SQL console, Cosmos and Service Bus
console facades, and the Azure SDK info/snippet routes."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:200]}")
    failed = failed or not ok


def call(method, path, **kw):
    return requests.request(method, BASE + path, timeout=60, **kw)


def main():
    tag = uuid.uuid4().hex[:6]

    r = call("GET", "/api/azure/console/summary")
    b = r.json() if r.ok else {}
    check("console summary has counts + total", r.ok and "vm" in b.get("counts", {}) and b.get("total") == sum(b["counts"].values()), r.text)
    r = call("POST", "/api/azure/nsg/reconcile")
    b = r.json() if r.ok else {}
    check("nsg reconcile reports enforcement state", r.ok and {"enforced", "ruleCount", "instances"} <= set(b), r.text)

    r = call("GET", "/api/console/azurevm/instances")
    b = r.json() if r.ok else {}
    check("azurevm instances list shape", r.ok and b.get("count") == len(b.get("instances", [])), r.text)
    r = call("POST", "/api/console/azurevm/instances/nope-" + tag + "/exec", json={"command": "id"})
    check("azurevm exec on unknown VM -> 404", r.status_code == 404, r.text)
    r = call("GET", f"/api/azure/vm/nope-{tag}/connect-info")
    check("connect-info unknown VM -> 404", r.status_code == 404, r.text)
    r = call("GET", f"/api/azure/vm/nope-{tag}/private-key.pem")
    check("private-key unknown VM -> 404", r.status_code == 404, r.text)

    r = call("GET", "/api/console/azure-sql/databases")
    b = r.json() if r.ok else {}
    db = b.get("default") or ""
    check("azure-sql databases list has a default db", r.ok and db and b.get("count", 0) >= 1, r.text)
    r = call("POST", "/api/console/azure-sql/execute", json={"db": db, "sql": "select 1 as one"})
    b = r.json() if r.ok else {}
    check("azure-sql execute select", r.ok and b.get("ok") and b.get("rows") == [[1]], r.text)
    r = call("POST", "/api/console/azure-sql/execute", json={"sql": " "})
    check("azure-sql execute empty sql -> 400", r.status_code == 400, r.text)
    r = call("GET", f"/api/console/azure-sql/databases/{db}/schema")
    check("azure-sql schema", r.ok, r.text)

    c = f"rt{tag}"
    r = call("POST", "/api/console/azure-cosmos/containers", json={"name": c})
    check("cosmos create container", r.ok, r.text)
    check("cosmos list container", c in call("GET", "/api/console/azure-cosmos/containers").text)
    check("cosmos get container", call("GET", f"/api/console/azure-cosmos/containers/{c}").ok)
    r = call("POST", f"/api/console/azure-cosmos/containers/{c}/items", json={"item": {"id": "a", "v": 1}})
    check("cosmos put item", r.ok, r.text)
    check("cosmos list items", '"a"' in call("GET", f"/api/console/azure-cosmos/containers/{c}/items").text)
    r = call("POST", f"/api/console/azure-cosmos/containers/{c}/query", json={"partition_key_value": "a"})
    check("cosmos query", r.ok and '"a"' in r.text, r.text)
    r = call("DELETE", f"/api/console/azure-cosmos/containers/{c}/items", json={"key": {"id": "a"}})
    check("cosmos delete item", r.ok, r.text)
    check("cosmos delete container", call("DELETE", f"/api/console/azure-cosmos/containers/{c}").ok)

    q, t = f"q{tag}", f"t{tag}"
    sp = "/api/console/azure-servicebus"
    check("sb create queue", call("POST", f"{sp}/queues", json={"name": q}).ok)
    check("sb list queues", q in call("GET", f"{sp}/queues").text)
    r = call("POST", f"{sp}/queues/{q}/send", json={"body": "hello"})
    check("sb send", r.ok and r.json().get("message_id"), r.text)
    r = call("GET", f"{sp}/queues/{q}/peek")
    check("sb peek", r.ok and r.json().get("count") == 1, r.text)
    r = call("POST", f"{sp}/queues/{q}/receive", json={})
    check("sb receive", r.ok and r.json().get("count") == 1, r.text)
    check("sb purge", call("POST", f"{sp}/queues/{q}/purge").json().get("purged") is True)
    r = call("POST", f"{sp}/topics", json={"name": t})
    ta = r.json().get("topic_arn") if r.ok else ""
    check("sb create topic", bool(ta), r.text)
    check("sb list topics", ta and ta in call("GET", f"{sp}/topics").text)
    check("sb subscribe", call("POST", f"{sp}/topics/subscribe", json={"topic_arn": ta, "queue": q}).json().get("subscribed") is True)
    r = call("GET", f"{sp}/topics/subscriptions", params={"topic_arn": ta})
    check("sb list subscriptions", r.ok and r.json().get("count") == 1, r.text)
    r = call("POST", f"{sp}/topics/publish", json={"topic_arn": ta, "message": "m1", "subject": "s"})
    check("sb publish fans out", r.ok and r.json().get("fanned_out_to") == 1, r.text)
    check("sb delete topic", call("POST", f"{sp}/topics/delete", json={"topic_arn": ta}).json().get("deleted") is True)
    check("sb delete queue", call("DELETE", f"{sp}/queues/{q}").json().get("deleted") is True)

    for lang, dep in (("python", "azure"), ("nodejs", "@azure")):
        r = call("GET", f"/api/providers/azure/sdk/{lang}")
        b = r.json() if r.ok else {}
        check(f"sdk info {lang}", r.ok and b.get("provider") == "azure" and dep in b.get("dependency", ""), r.text)
        r = call("GET", f"/api/providers/azure/sdk/{lang}/snippet")
        b = r.json() if r.ok else {}
        check(f"sdk snippet {lang} embeds endpoint", r.ok and b.get("language") == lang and b.get("endpoint", "") in b.get("snippet", "x"), r.text)

    sys.exit(1 if failed else 0)


main()
