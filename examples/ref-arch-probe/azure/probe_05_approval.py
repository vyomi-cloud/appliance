"""Component 5 Approval (assembled pattern; Azure has no waitForTaskToken orchestrator in the simulator):
request -> Service Bus topic/subscription (approver inbox, AMQP) -> approver calls a Function App function -> function writes the decision to the
ledger (Azure Table storage; also tried on Cosmos DB) -> the waiting caller sees the decision."""
import io, json, os, threading, time, zipfile, requests
from _common import *

P = Probe(5, "approval", "Approval: Service Bus inbox + Function + Table/Cosmos ledger")
B = endpoint(); ensure_rg(B)
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
TCS = f"DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey={KEY};TableEndpoint={B}/devstoreaccount1;"
S = {}


def func_app():
    from azure.mgmt.web import WebSiteManagementClient
    w = arm(WebSiteManagementClient, B)
    w.app_service_plans.begin_create_or_update(RG, "plan1", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
    w.web_apps.begin_create_or_update(RG, "approvals-fn", {"location": LOC, "kind": "functionapp", "server_farm_id": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Web/serverfarms/plan1",
        "site_config": {"app_settings": [{"name": "FUNCTIONS_WORKER_RUNTIME", "value": "python"}]}}).result()
    code = f'''import json
import azure.functions as func
from azure.data.tables import TableClient, UpdateMode
def main(req: func.HttpRequest) -> func.HttpResponse:
    b = req.get_json()
    t = TableClient.from_connection_string({TCS!r}, "ledger")
    t.upsert_entity({{"PartitionKey": "req", "RowKey": b["request_id"], "status": b["decision"], "approver": b["approver"]}}, mode=UpdateMode.REPLACE)
    return func.HttpResponse(json.dumps({{"ok": True, "request_id": b["request_id"]}}), mimetype="application/json")
'''
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("approve/__init__.py", code); zf.writestr("approve/function.json", "{}"); zf.writestr("host.json", "{}")
    r = requests.post(B + "/azure-data/functions/approvals-fn/api/zipdeploy", data=z.getvalue(), timeout=30)
    assert r.status_code == 200, (r.status_code, r.text[:150])
    return "function app + zipdeploy of approve()"


def table_basic():
    from azure.data.tables import TableServiceClient
    ts = TableServiceClient.from_connection_string(TCS)
    S["t"] = t = ts.create_table_if_not_exists("ledger")
    t.create_entity({"PartitionKey": "req", "RowKey": "probe", "status": "pending"})
    assert t.get_entity("req", "probe")["status"] == "pending"
    return "create_table + create_entity + get_entity"


def table_replace():
    from azure.data.tables import UpdateMode
    S["t"].update_entity({"PartitionKey": "req", "RowKey": "probe", "status": "approved"}, mode=UpdateMode.REPLACE)
    assert S["t"].get_entity("req", "probe")["status"] == "approved"
    S["t"].upsert_entity({"PartitionKey": "req", "RowKey": "probe2", "status": "x"}, mode=UpdateMode.REPLACE)
    return "update_entity(REPLACE) + upsert_entity(REPLACE)"


def table_merge():
    from azure.data.tables import UpdateMode
    S["t"].update_entity({"PartitionKey": "req", "RowKey": "probe", "approver": "mgr"}, mode=UpdateMode.MERGE)
    e = S["t"].get_entity("req", "probe")
    assert e["status"] == "approved" and e["approver"] == "mgr", dict(e)


def table_query():
    rows = list(S["t"].query_entities("status eq 'approved'"))
    assert [r["RowKey"] for r in rows] == ["probe"], rows


def table_etag():
    from azure.core import MatchConditions
    e = S["t"].get_entity("req", "probe")
    from azure.data.tables import UpdateMode
    S["t"].update_entity(e, mode=UpdateMode.REPLACE, etag=e.metadata["etag"], match_condition=MatchConditions.IfNotModified)
    try:
        S["t"].update_entity(e, mode=UpdateMode.REPLACE, etag='W/"datetime\'1999-01-01T00%3A00%3A00.0000000Z\'"', match_condition=MatchConditions.IfNotModified)
    except Exception as ex:
        return f"stale etag rejected: {type(ex).__name__}"
    raise AssertionError("stale etag was accepted (optimistic concurrency not enforced)")


def loop():
    """The whole approval loop. Entities for the inbox are seeded into the AMQP runtime store (see probe_02: ARM/REST creation does not reach it)."""
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    sb_seed(topic="approval-requests", sub="approver")
    rid = "req-" + str(int(time.monotonic()))
    S["t"].create_entity({"PartitionKey": "req", "RowKey": rid, "status": "pending"})
    seen = {}

    def approver():
        # WORKAROUND for the gap in late_delivery(): re-attach a short-lived receiver every 2 s instead of one long-lived receiver
        try:
            t0 = time.monotonic()
            while time.monotonic() - t0 < 20 and "fn" not in seen:
                with ServiceBusClient.from_connection_string(sb_conn(amqp_port())) as c:
                    with c.get_subscription_receiver("approval-requests", "approver", max_wait_time=2) as r:
                        for m in r.receive_messages(max_message_count=1, max_wait_time=2):
                            req = json.loads(b"".join(m.body).decode())
                            resp = requests.post(B + "/azure-data/functions/approvals-fn/api/approve", json={"request_id": req["request_id"], "decision": "approved", "approver": "manager1"}, timeout=30)
                            seen["fn"] = (resp.status_code, resp.text[-700:])
                            if resp.status_code == 200:
                                r.complete_message(m)
        except Exception as ex:  # surfaced in the assertion below
            seen["err"] = f"{type(ex).__name__}: {str(ex)[:150]}"
    th = threading.Thread(target=approver, daemon=True); th.start()
    with ServiceBusClient.from_connection_string(sb_conn(amqp_port())) as c:
        with c.get_topic_sender("approval-requests") as s:
            s.send_messages(ServiceBusMessage(json.dumps({"request_id": rid, "amount": 900})))
    t0 = time.monotonic(); status = "pending"
    while time.monotonic() - t0 < 25:
        status = S["t"].get_entity("req", rid)["status"]
        if status != "pending":
            break
        time.sleep(0.5)
    th.join(5)
    assert status == "approved", f"caller still sees '{status}' after {round(time.monotonic()-t0,1)}s; function call: {seen.get('fn')}; approver: {seen}"
    return f"caller saw '{status}' after {round(time.monotonic()-t0,1)}s (function replied {seen.get('fn')})"


def late_delivery():
    """A receiver that is ALREADY attached and waiting must be handed a message sent afterwards (what an approver service does)."""
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    sb_seed(topic="late-topic", sub="late-sub")
    got = {}

    def rx():
        with ServiceBusClient.from_connection_string(sb_conn(amqp_port())) as c:
            with c.get_subscription_receiver("late-topic", "late-sub", max_wait_time=10) as r:
                got["n"] = len(r.receive_messages(max_message_count=1, max_wait_time=10))
    th = threading.Thread(target=rx, daemon=True); th.start(); time.sleep(2)
    with ServiceBusClient.from_connection_string(sb_conn(amqp_port())) as c:
        with c.get_topic_sender("late-topic") as s:
            s.send_messages(ServiceBusMessage("late"))
    th.join(15)
    assert got.get("n") == 1, f"waiting receiver got {got.get('n')} messages within 10 s of the send"


def cosmos_ledger():
    from azure.mgmt.cosmosdb import CosmosDBManagementClient
    arm(CosmosDBManagementClient, B).database_accounts.begin_create_or_update(RG, "cosmos1", {"location": LOC, "kind": "GlobalDocumentDB", "locations": [{"location_name": LOC, "failover_priority": 0}],
        "database_account_offer_type": "Standard"}).result()
    from azure.cosmos import CosmosClient, PartitionKey
    from azure.core import MatchConditions
    c = CosmosClient(B + "/azure-data/cosmos/cosmos1", credential=KEY, connection_verify=False)
    ct = c.create_database_if_not_exists("ops").create_container_if_not_exists("ledger", partition_key=PartitionKey(path="/id"))
    ct.upsert_item({"id": "r1", "status": "pending"})
    it = ct.read_item("r1", partition_key="r1")
    it["status"] = "approved"
    ct.replace_item("r1", it, etag=it["_etag"], match_condition=MatchConditions.IfNotModified)
    S["cosmos_item"] = ct.read_item("r1", partition_key="r1")
    assert [x["status"] for x in ct.query_items("SELECT * FROM c WHERE c.status = 'approved'", enable_cross_partition_query=True)] == ["approved"]
    try:
        ct.replace_item("r1", it, etag='"stale"', match_condition=MatchConditions.IfNotModified)
        raise AssertionError("stale etag accepted")
    except AssertionError:
        raise
    except Exception as ex:
        return f"upsert/read/replace/query ok; stale etag -> {type(ex).__name__}"


def cosmos_replace_by_self_link():
    """replace_item(<item dict>) resolves the item through the _self link the service returned (dbs/{rid}/colls/{rid}/docs/{rid})."""
    from azure.cosmos import CosmosClient
    ct = CosmosClient(B + "/azure-data/cosmos/cosmos1", credential=KEY, connection_verify=False).get_database_client("ops").get_container_client("ledger")
    it = ct.read_item("r1", partition_key="r1")
    it["status"] = "closed"
    ct.replace_item(it, it)


def cosmos_patch():
    from azure.cosmos import CosmosClient
    ct = CosmosClient(B + "/azure-data/cosmos/cosmos1", credential=KEY, connection_verify=False).get_database_client("ops").get_container_client("ledger")
    ct.patch_item("r1", partition_key="r1", patch_operations=[{"op": "set", "path": "/approver", "value": "mgr"}])
    assert ct.read_item("r1", partition_key="r1")["approver"] == "mgr"


def backend_is_real():
    """Where does Table data really live? The doc proposes Azurite for 'real backend'. Compare against the capability register."""
    import json as _j
    d = _j.load(open(os.path.join(repo_root(), "core", "capabilities", "backends", "azure.json")))
    note = d["storage"]["offline"]["notes"]
    assert "not in Azurite" not in note, "Table data is held in Vyomi's own state slots, NOT in Azurite: " + note[:230]


if P.step("Function App + zipdeploy of an approve() function that writes the ledger (azure.functions + azure-data-tables)", func_app):
    pass
if P.step("Table ledger: create table + entity, read back (azure-data-tables)", table_basic):
    P.step("Table: replace-mode update + upsert (PUT)", table_replace)
    P.step("Table: merge-mode update (PATCH)", table_merge)
    P.step("Table: OData $filter query", table_query)
    P.step("Table: ETag optimistic concurrency (If-Match) accepted/rejected", table_etag)
    P.step("FULL LOOP: request -> Service Bus (AMQP) -> approver -> Function -> Table -> caller sees 'approved'", loop)
P.step("Service Bus: an already-attached receiver is handed a message sent later (live delivery)", late_delivery)
P.step("Cosmos ledger (azure-cosmos): upsert/read/replace-with-etag/SQL query", cosmos_ledger)
P.step("Cosmos ledger: replace_item(item dict) via the returned _self link", cosmos_replace_by_self_link)
P.step("Cosmos ledger: patch_item", cosmos_patch)
P.step("Table storage is backed by a real engine (Azurite) as REFERENCE-ARCH doc proposes", backend_is_real)
P.finish()
