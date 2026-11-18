"""VYOMI_AZURE_REAL_BACKENDS=1: the REAL Azurite is the simulator's Azure Table (and Storage Queue) data plane.

Proves, with the unmodified azure-data-tables / azure-storage-queue / azure-mgmt-storage SDKs:
  (a) the full Table scenario of test_azure_table_wire_sdk.py (PATCH/PUT, $filter, $select, paging, ETag 412, upsert,
      submit_transaction) passes THROUGH the simulator with the data held by Azurite;
  (b) the SAME entities are visible directly against the Azurite endpoint with the standard devstoreaccount1 connection
      string (the way developers use Azurite), in both directions, and an ETag taken from one side works on the other;
  (c) the ARM control plane (storage account + table records via azure-mgmt-storage) keeps working with the mode on;
  (d) Storage Queue messages sent through the simulator are received directly from Azurite and vice versa.

Needs docker + the LOCAL image mcr.microsoft.com/azure-storage/azurite (never pulled here) and the Azure SDKs; SKIPs
cleanly (exit 0, "[SKIP]") otherwise. Container name vyomi-test-azreal-<tag>; only that exact name is removed.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_real_backends.py
"""
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
IMG = "mcr.microsoft.com/azure-storage/azurite:latest"
NAME = "vyomi-test-azreal-" + uuid.uuid4().hex[:6]


def skip(why):
    print(f"[SKIP] {why}")
    sys.exit(0)


def sh(*a, timeout=120):
    return subprocess.run(a, capture_output=True, text=True, timeout=timeout)


try:
    from azure.data.tables import TableServiceClient
    from azure.storage.queue import QueueServiceClient
except ImportError:
    skip("azure-data-tables / azure-storage-queue not installed")
import _az_inproc as h
import _az_table_scenario as sc


PROC = None


def start_azurite():
    """Docker image first; or AZURITE_BIN=<path to the npm `azurite` binary> (same real Azurite, no docker needed)."""
    global PROC
    if os.environ.get("AZURITE_BIN"):
        import tempfile
        qp, tp = h.freeport(), h.freeport()
        PROC = subprocess.Popen([os.environ["AZURITE_BIN"], "--location", tempfile.mkdtemp(prefix="azurite-"), "--silent", "--loose",
                                 "--skipApiVersionCheck", "--blobPort", str(h.freeport()), "--queuePort", str(qp), "--tablePort", str(tp)])
        return _wait(qp, tp)
    try:
        if sh("docker", "info").returncode != 0:
            skip("docker daemon not running")
        if sh("docker", "image", "inspect", IMG).returncode != 0:
            skip(f"image {IMG} not present locally (this test never pulls it)")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        skip("docker CLI not installed / not responding")
    qp, tp = h.freeport(), h.freeport()
    r = sh("docker", "run", "-d", "--name", NAME, "-p", f"127.0.0.1:{qp}:10001", "-p", f"127.0.0.1:{tp}:10002", IMG, "azurite",
           "--blobHost", "0.0.0.0", "--queueHost", "0.0.0.0", "--tableHost", "0.0.0.0", "--skipApiVersionCheck", "--loose")
    if r.returncode:
        raise RuntimeError(r.stderr)
    return _wait(qp, tp)


def _wait(qp, tp):
    import socket
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", tp), 1).close()
            socket.create_connection(("127.0.0.1", qp), 1).close()
            time.sleep(0.5)
            return qp, tp
        except OSError:
            time.sleep(1)
    raise RuntimeError("azurite did not come up")


def main():
    qp, tp = start_azurite()
    try:
        os.environ.update({"VYOMI_AZURE_REAL_BACKENDS": "1", "VYOMI_AZURE_AZURITE_ENDPOINT": "http://127.0.0.1",
                           "VYOMI_AZURE_AZURITE_TABLE_PORT": str(tp), "VYOMI_AZURE_AZURITE_QUEUE_PORT": str(qp)})
        base = h.start_sim()
        from core import azure_real_backends as arb
        h.ok("real mode installed in the appliance app", arb.status()["installed"], str(arb.status()))
        via = TableServiceClient.from_connection_string(h.table_cs(base))
        direct_cs = (f"DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey={h.KEY};"
                     f"TableEndpoint=http://127.0.0.1:{tp}/devstoreaccount1;")
        direct = TableServiceClient.from_connection_string(direct_cs)

        # (a) full scenario through the simulator
        sc.run(via, "via-simulator: ")

        # (b) one store, two doors
        from azure.core import MatchConditions
        from azure.data.tables import UpdateMode
        tn = "approvalledger"
        vt = via.create_table_if_not_exists(tn)
        dt = direct.get_table_client(tn)
        h.ok("table created through the simulator exists in Azurite", tn in [x.name for x in direct.list_tables()])
        vt.create_entity({"PartitionKey": "req", "RowKey": "r1", "status": "pending"})
        h.ok("entity written via simulator is read directly from Azurite", dt.get_entity("req", "r1")["status"] == "pending")
        dt.upsert_entity({"PartitionKey": "req", "RowKey": "r2", "status": "approved"})
        h.ok("entity written directly in Azurite is read via simulator", vt.get_entity("req", "r2")["status"] == "approved")
        h.ok("filter via simulator sees both writers", sorted(x["RowKey"] for x in vt.query_entities("PartitionKey eq 'req'")) == ["r1", "r2"])
        et = dt.get_entity("req", "r1").metadata["etag"]
        vt.update_entity({"PartitionKey": "req", "RowKey": "r1", "status": "approved"}, mode=UpdateMode.MERGE, etag=et,
                         match_condition=MatchConditions.IfNotModified)
        h.ok("etag taken directly from Azurite is honoured by the simulator", dt.get_entity("req", "r1")["status"] == "approved")
        direct.create_table_if_not_exists("directonly")
        h.ok("table created directly in Azurite is listed via simulator", "directonly" in [x.name for x in via.list_tables()])
        # the simulator's own in-process Table store must NOT be where the data lives
        from core import appliance_stores as aps, app_context as ctx
        tok = ctx.REQUEST_PROVIDER.set("azure")
        try:
            own = list(aps.table_store().tables)
        finally:
            ctx.REQUEST_PROVIDER.reset(tok)
        h.ok("data is not held in the simulator's own Table store", tn not in own and "directonly" not in own, str(own))

        # (c) ARM control plane keeps working and stays consistent
        from azure.mgmt.resource.resources import ResourceManagementClient
        from azure.mgmt.storage import StorageManagementClient
        rg = "rg-azreal"
        h.arm(ResourceManagementClient, base).resource_groups.create_or_update(rg, {"location": "eastus"})
        sm = h.arm(StorageManagementClient, base)
        acct = "facilitiesdocs"
        sm.storage_accounts.begin_create(rg, acct, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}).result()
        sm.table.create(rg, acct, "armtable")
        h.ok("ARM: storage account + table record created and listed",
             "armtable" in [x.name for x in sm.table.list(rg, acct)] and sm.storage_accounts.get_properties(rg, acct).name == acct)
        h.ok("ARM: keys still issued", len(sm.storage_accounts.list_keys(rg, acct)["keys"]) >= 1)
        h.ok("data plane unaffected by ARM calls", tn in [x.name for x in via.list_tables()])

        # (d) Storage Queue
        qcs_via = f"DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey={h.KEY};QueueEndpoint={base}/devstoreaccount1;"
        qcs_direct = f"DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey={h.KEY};QueueEndpoint=http://127.0.0.1:{qp}/devstoreaccount1;"
        qv = QueueServiceClient.from_connection_string(qcs_via).create_queue("approvals")
        qd = QueueServiceClient.from_connection_string(qcs_direct).get_queue_client("approvals")
        qv.send_message("hello-from-simulator")
        got = [m.content for m in qd.receive_messages(max_messages=1)]
        h.ok("queue message sent via simulator is received directly from Azurite", got == ["hello-from-simulator"], str(got))
        qd.send_message("hello-from-azurite")
        got = [m.content for m in qv.receive_messages(max_messages=1)]
        h.ok("queue message sent directly is received via simulator", got == ["hello-from-azurite"], str(got))
    finally:
        if PROC is not None:
            PROC.terminate()
        else:
            sh("docker", "rm", "-f", NAME)
    print(f"\n{len(h.FAILS)} failure(s)" if h.FAILS else "\nAll PASS")
    sys.exit(1 if h.FAILS else 0)


if __name__ == "__main__":
    main()
