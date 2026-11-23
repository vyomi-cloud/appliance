"""Azure operation map: ARM path + verb / data-plane request -> RBAC action or dataAction (core/iam_engine/map_azure.py)."""
import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.iam_engine import map_azure  # noqa: E402

S = "/subscriptions/s1"
RG = S + "/resourceGroups/rg1"
SA = RG + "/providers/Microsoft.Storage/storageAccounts/sa"
ARM = [
    ("GET", "/subscriptions", "Microsoft.Resources/subscriptions/read"),
    ("GET", S, "Microsoft.Resources/subscriptions/read"),
    ("GET", S + "/resourcegroups", "Microsoft.Resources/subscriptions/resourceGroups/read"),
    ("GET", RG, "Microsoft.Resources/subscriptions/resourceGroups/read"),
    ("PUT", RG, "Microsoft.Resources/subscriptions/resourceGroups/write"),
    ("DELETE", RG, "Microsoft.Resources/subscriptions/resourceGroups/delete"),
    ("GET", RG + "/providers/Microsoft.Compute/virtualMachines/vm1", "Microsoft.Compute/virtualMachines/read"),
    ("PUT", RG + "/providers/Microsoft.Compute/virtualMachines/vm1?api-version=2023-09-01", "Microsoft.Compute/virtualMachines/write"),
    ("PATCH", RG + "/providers/Microsoft.Compute/virtualMachines/vm1", "Microsoft.Compute/virtualMachines/write"),
    ("DELETE", RG + "/providers/Microsoft.Compute/virtualMachines/vm1", "Microsoft.Compute/virtualMachines/delete"),
    ("GET", RG + "/providers/Microsoft.Compute/virtualMachines", "Microsoft.Compute/virtualMachines/read"),
    ("GET", S + "/providers/Microsoft.Compute/virtualMachines", "Microsoft.Compute/virtualMachines/read"),
    ("POST", RG + "/providers/Microsoft.Compute/virtualMachines/vm1/start", "Microsoft.Compute/virtualMachines/start/action"),
    ("POST", RG + "/providers/Microsoft.Compute/virtualMachines/vm1/powerOff", "Microsoft.Compute/virtualMachines/powerOff/action"),
    ("POST", RG + "/providers/Microsoft.Compute/virtualMachines/vm1/restart", "Microsoft.Compute/virtualMachines/restart/action"),
    ("POST", RG + "/providers/Microsoft.Compute/virtualMachines/vm1/runCommand", "Microsoft.Compute/virtualMachines/runCommand/action"),
    ("PUT", SA, "Microsoft.Storage/storageAccounts/write"),
    ("POST", SA + "/listKeys", "Microsoft.Storage/storageAccounts/listKeys/action"),
    ("POST", SA + "/regenerateKey", "Microsoft.Storage/storageAccounts/regenerateKey/action"),
    ("GET", SA + "/blobServices/default/containers/c", "Microsoft.Storage/storageAccounts/blobServices/containers/read"),
    ("PUT", SA + "/blobServices/default/containers/c", "Microsoft.Storage/storageAccounts/blobServices/containers/write"),
    ("DELETE", SA + "/blobServices/default/containers/c", "Microsoft.Storage/storageAccounts/blobServices/containers/delete"),
    ("GET", SA + "/blobServices/default/containers", "Microsoft.Storage/storageAccounts/blobServices/containers/read"),
    ("POST", S + "/providers/Microsoft.Storage/checkNameAvailability", "Microsoft.Storage/checknameavailability/read"),
    ("PUT", RG + "/providers/Microsoft.Resources/deployments/d1", "Microsoft.Resources/deployments/write"),
    ("GET", RG + "/providers/Microsoft.Resources/deployments/d1", "Microsoft.Resources/deployments/read"),
    ("POST", RG + "/providers/Microsoft.Resources/deployments/d1/validate", "Microsoft.Resources/deployments/validate/action"),
    ("POST", RG + "/providers/Microsoft.Resources/deployments/d1/cancel", "Microsoft.Resources/deployments/cancel/action"),
    ("PUT", RG + "/deployments/d2", "Microsoft.Resources/deployments/write"),
    ("PUT", S + "/providers/Microsoft.Authorization/roleAssignments/ra1", "Microsoft.Authorization/roleAssignments/write"),
    ("DELETE", S + "/providers/Microsoft.Authorization/roleAssignments/ra1", "Microsoft.Authorization/roleAssignments/delete"),
    ("GET", S + "/providers/Microsoft.Authorization/roleDefinitions", "Microsoft.Authorization/roleDefinitions/read"),
    ("PUT", RG + "/providers/Microsoft.Compute/virtualMachines/vm/providers/Microsoft.Authorization/roleAssignments/ra", "Microsoft.Authorization/roleAssignments/write"),
    ("PUT", RG + "/providers/Microsoft.KeyVault/vaults/kv", "Microsoft.KeyVault/vaults/write"),
    ("PUT", RG + "/providers/Microsoft.Network/virtualNetworks/vnet/subnets/sn", "Microsoft.Network/virtualNetworks/subnets/write"),
    ("GET", RG + "/providers/Microsoft.Network/networkSecurityGroups/nsg", "Microsoft.Network/networkSecurityGroups/read"),
    ("PUT", RG + "/providers/Microsoft.Sql/servers/srv/databases/db", "Microsoft.Sql/servers/databases/write"),
    ("PUT", RG + "/providers/Microsoft.ContainerService/managedClusters/aks", "Microsoft.ContainerService/managedClusters/write"),
    ("POST", RG + "/providers/Microsoft.ContainerService/managedClusters/aks/listClusterAdminCredential", "Microsoft.ContainerService/managedClusters/listClusterAdminCredential/action"),
    ("PUT", RG + "/providers/Microsoft.Web/sites/app", "Microsoft.Web/sites/write"),
    ("PUT", RG + "/providers/Microsoft.DocumentDB/databaseAccounts/cos", "Microsoft.DocumentDB/databaseAccounts/write"),
    ("PUT", RG + "/providers/Microsoft.ServiceBus/namespaces/ns/queues/q", "Microsoft.ServiceBus/namespaces/queues/write"),
    ("GET", S + "/providers/Microsoft.Compute/locations/eastus/vmSizes", "Microsoft.Compute/locations/vmSizes/read"),
]


@pytest.mark.parametrize("method,path,action", ARM, ids=[f"{a[0]} {a[1][-55:]}" for a in ARM])
def test_arm(method, path, action):
    got = map_azure.required(method, path)
    assert len(got) == 1 and got[0]["action"].lower() == action.lower(), got
    assert got[0]["data"] is False and got[0]["resource"].startswith("/")


def test_arm_action_uses_catalog_casing():
    assert map_azure.required("POST", S + "/providers/Microsoft.Storage/checkNameAvailability")[0]["action"] == \
        "Microsoft.Storage/checknameavailability/read"


B = "https://sa.blob.core.windows.net"
DATA = [
    ("GET", B + "/c/b.txt", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"),
    ("HEAD", B + "/c/b.txt", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"),
    ("PUT", B + "/c/b.txt", {"x-ms-blob-type": "BlockBlob"}, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"),
    ("PUT", B + "/c/b.txt?comp=block&blockid=AA", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"),
    ("PUT", B + "/c/log.txt", {"x-ms-blob-type": "AppendBlob"}, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action"),
    ("PUT", B + "/c/log.txt?comp=appendblock", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action"),
    ("DELETE", B + "/c/b.txt", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete"),
    ("GET", B + "/c/b.txt?comp=tags", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read"),
    ("PUT", B + "/c/b.txt?comp=tags", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/write"),
    ("GET", B + "/c?restype=container&comp=list", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"),
    ("PUT", B + "/c?restype=container", None, "Microsoft.Storage/storageAccounts/blobServices/containers/write"),
    ("DELETE", B + "/c?restype=container", None, "Microsoft.Storage/storageAccounts/blobServices/containers/delete"),
    ("GET", B + "/?comp=list", None, "Microsoft.Storage/storageAccounts/blobServices/containers/read"),
    ("GET", "/azure-data/blob/sa/c/b.txt", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"),
    ("PUT", "/azure-data/blob/sa/c/b.txt", None, "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"),
    ("POST", "https://sa.queue.core.windows.net/q/messages", None, "Microsoft.Storage/storageAccounts/queueServices/queues/messages/add/action"),
    ("GET", "https://sa.queue.core.windows.net/q/messages?numofmessages=5", None, "Microsoft.Storage/storageAccounts/queueServices/queues/messages/process/action"),
    ("GET", "https://sa.queue.core.windows.net/q/messages?peekonly=true", None, "Microsoft.Storage/storageAccounts/queueServices/queues/messages/read"),
    ("DELETE", "https://sa.queue.core.windows.net/q/messages/m1?popreceipt=x", None, "Microsoft.Storage/storageAccounts/queueServices/queues/messages/delete"),
    ("PUT", "https://sa.queue.core.windows.net/q", None, "Microsoft.Storage/storageAccounts/queueServices/queues/write"),
    ("GET", "https://sa.table.core.windows.net/t()", None, "Microsoft.Storage/storageAccounts/tableServices/tables/entities/read"),
    ("POST", "https://sa.table.core.windows.net/t", None, "Microsoft.Storage/storageAccounts/tableServices/tables/entities/add/action"),
    ("MERGE", "https://sa.table.core.windows.net/t(PartitionKey='a',RowKey='b')", None, "Microsoft.Storage/storageAccounts/tableServices/tables/entities/update/action"),
    ("DELETE", "https://sa.table.core.windows.net/t(PartitionKey='a',RowKey='b')", None, "Microsoft.Storage/storageAccounts/tableServices/tables/entities/delete"),
    ("GET", "https://kv1.vault.azure.net/secrets/db-pass", None, "Microsoft.KeyVault/vaults/secrets/getSecret/action"),
    ("GET", "https://kv1.vault.azure.net/secrets/db-pass/abc123", None, "Microsoft.KeyVault/vaults/secrets/getSecret/action"),
    ("PUT", "https://kv1.vault.azure.net/secrets/db-pass", None, "Microsoft.KeyVault/vaults/secrets/setSecret/action"),
    ("GET", "https://kv1.vault.azure.net/secrets", None, "Microsoft.KeyVault/vaults/secrets/readMetadata/action"),
    ("DELETE", "https://kv1.vault.azure.net/secrets/db-pass", None, "Microsoft.KeyVault/vaults/secrets/delete"),
    ("POST", "https://kv1.vault.azure.net/keys/k/create", None, "Microsoft.KeyVault/vaults/keys/create/action"),
    ("POST", "https://kv1.vault.azure.net/keys/k/ver/sign", None, "Microsoft.KeyVault/vaults/keys/sign/action"),
    ("POST", "https://kv1.vault.azure.net/keys/k/ver/wrapkey", None, "Microsoft.KeyVault/vaults/keys/wrap/action"),
    ("POST", "https://kv1.vault.azure.net/keys/k/ver/decrypt", None, "Microsoft.KeyVault/vaults/keys/decrypt/action"),
    ("GET", "https://kv1.vault.azure.net/keys/k", None, "Microsoft.KeyVault/vaults/keys/read"),
    ("POST", "https://kv1.vault.azure.net/certificates/c/create", None, "Microsoft.KeyVault/vaults/certificates/create/action"),
    ("GET", "https://kv1.vault.azure.net/certificates/c", None, "Microsoft.KeyVault/vaults/certificates/read"),
    ("POST", "https://ns1.servicebus.windows.net/q1/messages", None, "Microsoft.ServiceBus/namespaces/messages/send/action"),
    ("POST", "https://ns1.servicebus.windows.net/q1/messages/head", None, "Microsoft.ServiceBus/namespaces/messages/receive/action"),
    ("DELETE", "https://ns1.servicebus.windows.net/q1/messages/head", None, "Microsoft.ServiceBus/namespaces/messages/receive/action"),
    ("POST", "https://cos.documents.azure.com/dbs/d/colls/c/docs", None, "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/create"),
    ("POST", "https://cos.documents.azure.com/dbs/d/colls/c/docs", {"x-ms-documentdb-isquery": "True"}, "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/executeQuery"),
    ("GET", "https://cos.documents.azure.com/dbs/d/colls/c/docs/id1", None, "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/read"),
    ("DELETE", "https://cos.documents.azure.com/dbs/d/colls/c/docs/id1", None, "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/delete"),
    ("GET", "https://cfg1.azconfig.io/kv?key=*", None, "Microsoft.AppConfiguration/configurationStores/keyValues/read"),
    ("PUT", "https://cfg1.azconfig.io/kv/app:key", None, "Microsoft.AppConfiguration/configurationStores/keyValues/write"),
    ("DELETE", "https://cfg1.azconfig.io/kv/app:key", None, "Microsoft.AppConfiguration/configurationStores/keyValues/delete"),
]


@pytest.mark.parametrize("method,url,headers,action", DATA, ids=[f"{d[0]} {d[1][8:70]}" for d in DATA])
def test_data_plane(method, url, headers, action):
    got = map_azure.required(method, url, headers=headers)
    assert len(got) == 1 and got[0]["action"].lower() == action.lower(), got
    assert got[0]["data"] is True


def test_non_azure_path_unmapped():
    assert map_azure.required("GET", "/api/health") == []


def _catalog():
    acts, dacts = set(), set()
    for f in glob.glob(os.path.join(ROOT, "core/iam_catalog/azure/*.json")):
        d = json.load(open(f))
        acts |= set(d["actions"])
        dacts |= set(d["dataActions"])
    return acts, dacts


# Data actions that real Azure defines but the verbatim catalog does not carry (Cosmos SQL data RBAC is a separate role system).
KNOWN_NOT_IN_CATALOG_PREFIX = ("Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/", "Microsoft.DocumentDB/databaseAccounts/readMetadata")


def test_every_emitted_action_is_in_the_catalog_and_coverage(capsys):
    acts, dacts = _catalog()
    both = {a.lower() for a in acts | dacts}
    emitted_arm = [map_azure.required(m, p)[0]["action"] for m, p, _ in ARM]
    emitted_data = [map_azure.required(m, u, headers=h)[0]["action"] for m, u, h, _ in DATA]
    missing = [a for a in emitted_arm + emitted_data if a.lower() not in both and not a.startswith(KNOWN_NOT_IN_CATALOG_PREFIX)]
    assert missing == []
    in_cat = sum(a.lower() in both for a in emitted_arm + emitted_data)
    print("emitted %d actions in tests, %d verbatim in catalog, %d known Cosmos-data-RBAC outside it" %
          (len(emitted_arm + emitted_data), in_cat, len(emitted_arm + emitted_data) - in_cat))


def test_catalog_roundtrip_coverage(capsys):
    """Synthesise a request for every catalog control-plane action and check the mapper reproduces it."""
    acts, _ = _catalog()
    ok = tot = 0
    bad = []
    for a in sorted(acts):
        parts = a.split("/")
        if len(parts) < 3:
            continue
        ns, rest = parts[0], parts[1:]
        verb = rest[-1].lower()
        if verb == "action":
            types, op = rest[:-2], rest[-2]
            method = "POST"
            path = "/".join("%s/n%d" % (t, i) for i, t in enumerate(types))
            path = (path + "/" if path else "") + op
        elif verb in ("read", "write", "delete"):
            types = rest[:-1]
            method = {"read": "GET", "write": "PUT", "delete": "DELETE"}[verb]
            path = "/".join("%s/n%d" % (t, i) for i, t in enumerate(types))
        else:
            continue
        url = "/subscriptions/s/resourceGroups/rg/providers/%s/%s" % (ns, path)
        tot += 1
        got = map_azure.required(method, url)
        if got and got[0]["action"].lower() == a.lower():
            ok += 1
        else:
            bad.append(a)
    print("Azure catalog round-trip: %d / %d (%.1f%%)" % (ok, tot, 100.0 * ok / tot))
    assert ok / tot > 0.95, bad[:10]
