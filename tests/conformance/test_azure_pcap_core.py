"""Network Watcher packet capture (core/azure_pcap_core.py): real ARM lifecycle (create+start / get / list / stop / queryStatus /
delete), validation, filters, flow-derived libpcap written to network-watcher-logs of the target storage account, time/bytes limits.
Run: PYTHONPATH=. python tests/conformance/test_azure_pcap_core.py"""
import struct
import time

from core.azure_arm_core import AzureArm
from core import azure_blob_core as blob, azure_pcap_core as pc

SUB, RG = "00000000-0000-0000-0000-0000000000aa", "pc-rg"
RGP = f"/subscriptions/{SUB}/resourceGroups/{RG}"
NET = f"{RGP}/providers/Microsoft.Network"
AzureArm.STRICT_SUBSCRIPTION = False


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def run():
    a = AzureArm()
    a.blob_store = blob.AzureBlobStore()
    h = lambda m, p, b=None, v="2023-11-01": a.handle(m, p, {"api-version": v}, b)
    h("PUT", RGP, {"location": "eastus"}, "2021-04-01")
    h("PUT", f"{RGP}/providers/Microsoft.Storage/storageAccounts/pcstore", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, "2023-01-01")
    nsg = h("PUT", f"{NET}/networkSecurityGroups/pc-nsg", {"location": "eastus", "properties": {"securityRules": []}})["body"]
    h("PUT", f"{NET}/virtualNetworks/v1", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.90.0.0/16"]}, "subnets": [
        {"name": "s", "properties": {"addressPrefix": "10.90.1.0/24", "networkSecurityGroup": {"id": nsg["id"]}}}]}})
    nic = h("PUT", f"{NET}/networkInterfaces/n1", {"location": "eastus", "properties": {"ipConfigurations": [{"name": "c", "properties": {"subnet": {"id": f"{NET}/virtualNetworks/v1/subnets/s"}}}]}})["body"]
    ip = nic["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"]
    h("PUT", f"{RGP}/providers/Microsoft.Compute/virtualMachines/vm1", {"location": "eastus", "properties": {"networkProfile": {"networkInterfaces": [{"id": nic["id"]}]}}}, "2023-09-01")
    h("PUT", f"{RGP}/providers/Microsoft.Compute/virtualMachines/vmw", {"location": "westus", "properties": {}}, "2023-09-01")
    NW = f"{NET}/networkWatchers/NetworkWatcher_eastus"
    h("PUT", NW, {"location": "eastus"})
    VM = f"{RGP}/providers/Microsoft.Compute/virtualMachines/vm1"
    ST = f"{RGP}/providers/Microsoft.Storage/storageAccounts/pcstore"
    body = lambda **kw: {"properties": {"target": VM, "storageLocation": {"storageId": ST}, **kw}}
    put = lambda n, b: h("PUT", f"{NW}/packetCaptures/{n}", b)

    # validation
    ok("missing network watcher -> 404", h("PUT", f"{NET}/networkWatchers/nope/packetCaptures/x", body())["status"] == 404)
    ok("missing target -> 400", put("x", {"properties": {"storageLocation": {"storageId": ST}}})["status"] == 400)
    ok("unknown VM -> 400", put("x", {"properties": {"target": VM + "zz", "storageLocation": {"storageId": ST}}})["status"] == 400)
    ok("target in another region -> 400", put("x", {"properties": {"target": f"{RGP}/providers/Microsoft.Compute/virtualMachines/vmw", "storageLocation": {"storageId": ST}}})["status"] == 400)
    ok("no storage/file -> 400", put("x", {"properties": {"target": VM}})["status"] == 400)
    ok("unknown storage -> 400", put("x", {"properties": {"target": VM, "storageLocation": {"storageId": ST + "zz"}}})["status"] == 400)
    ok("timeLimit > 18000 -> 400", put("x", body(timeLimitInSeconds=18001))["status"] == 400)
    ok("totalBytes > 1GiB -> 400", put("x", body(totalBytesPerSession=2 ** 30 + 1))["status"] == 400)
    ok("bad filter protocol -> 400", put("x", body(filters=[{"protocol": "ICMP"}]))["status"] == 400)
    ok("bad filter IP -> 400", put("x", body(filters=[{"remoteIPAddress": "300.1.1.1"}]))["status"] == 400)
    ok("bad filter port -> 400", put("x", body(filters=[{"localPort": "90-80"}]))["status"] == 400)

    # create + start
    r = put("cap1", body(filters=[{"protocol": "TCP", "remoteIPAddress": "203.0.113.0/24", "remotePort": "443"}], bytesToCapturePerPacket=0))
    ok("PUT creates (201) with real shape", r["status"] == 201 and r["body"]["type"] == "Microsoft.Network/networkWatchers/packetCaptures"
       and r["body"]["properties"]["timeLimitInSeconds"] == 18000 and r["body"]["properties"]["totalBytesPerSession"] == 2 ** 30
       and r["body"]["properties"]["storageLocation"]["storagePath"].startswith("https://pcstore.blob.core.windows.net/network-watcher-logs/subscriptions/"), r)
    ok("no private keys leak", not any(k.startswith("_") for k in r["body"]))
    ok("duplicate name rejected", put("cap1", body())["status"] == 400)
    st = h("POST", f"{NW}/packetCaptures/cap1/queryStatus")["body"]
    ok("queryStatus Running", st["packetCaptureStatus"] == "Running" and st["name"] == "cap1" and st["captureStartTime"], st)
    ok("GET + list", h("GET", f"{NW}/packetCaptures/cap1")["status"] == 200 and len(h("GET", f"{NW}/packetCaptures")["body"]["value"]) == 1)

    # flows: only the allowed, filter-matching ones from the shared evaluator are captured
    def verify(remote, port, direction="Outbound"):
        return h("POST", f"{NW}/ipFlowVerify", {"targetResourceId": VM, "direction": direction, "protocol": "TCP", "localPort": "50000" if direction == "Outbound" else str(port),
                                                "remotePort": str(port) if direction == "Outbound" else "50000", "localIPAddress": ip, "remoteIPAddress": remote})["body"]
    ok("evaluator allows 203.0.113.9:443", verify("203.0.113.9", 443)["access"] == "Allow")
    ok("evaluator allows 203.0.113.9:80 (filtered out by remotePort)", verify("203.0.113.9", 80)["access"] == "Allow")
    ok("evaluator denies inbound from internet (not captured)", verify("198.51.100.7", 80, "Inbound")["access"] == "Deny")
    st = h("POST", f"{NW}/packetCaptures/cap1/queryStatus")["body"]
    ok("exactly the one matching allowed flow captured", st["vyomiSummary"]["packets"] == 1, st)

    # stop -> .cap in storage
    ok("stop 200", h("POST", f"{NW}/packetCaptures/cap1/stop")["status"] == 200)
    st = h("POST", f"{NW}/packetCaptures/cap1/queryStatus")["body"]
    ok("Stopped / Manual", st["packetCaptureStatus"] == "Stopped" and st["stopReason"] == "Manual", st)
    key = next((k for k in a.blob_store.blobs if k == "pcstore/network-watcher-logs"), None)
    ok("container network-watcher-logs created in the storage account", key is not None, list(a.blob_store.blobs))
    (name, blobrec), = a.blob_store.blobs[key].items()
    data = blobrec["data"]
    ok("blob path has real layout", name.startswith("subscriptions/") and "/virtualmachines/vm1/" in name and name.endswith(".cap") and "packetcapture_" in name, name)
    magic, vmaj, vmin, _, _, snap, link = struct.unpack("<IHHiIII", data[:24])
    ok("valid libpcap header", magic == 0xA1B2C3D4 and (vmaj, vmin) == (2, 4) and link == 1)
    sec, usec, caplen, orig = struct.unpack("<IIII", data[24:40])
    fr = data[40:40 + caplen]
    ok("one packet record, truncated frame", len(data) == 40 + caplen and orig >= caplen)
    ok("IPv4/TCP, src=VM dst=203.0.113.9 :443", fr[12:14] == b"\x08\x00" and fr[23] == 6 and fr[26:30] == bytes(int(x) for x in ip.split("."))
       and fr[30:34] == bytes([203, 0, 113, 9]) and struct.unpack("!HH", fr[34:38]) == (50000, 443))
    ok("IP header checksum valid", pc._csum(fr[14:34]) == 0)
    ok("stop is idempotent", h("POST", f"{NW}/packetCaptures/cap1/stop")["status"] == 200)
    ok("delete", h("DELETE", f"{NW}/packetCaptures/cap1")["status"] in (202, 204) and h("GET", f"{NW}/packetCaptures/cap1")["status"] == 404)
    ok("file kept after delete", len(a.blob_store.blobs[key]) == 1)

    # bytes limit + time limit
    put("cap2", body(bytesToCapturePerPacket=40, totalBytesPerSession=100))
    verify("203.0.113.9", 443)
    verify("203.0.113.9", 8443)
    st = h("POST", f"{NW}/packetCaptures/cap2/queryStatus")["body"]
    ok("BytesExceeded stops the capture", st["packetCaptureStatus"] == "Stopped" and st["stopReason"] == "BytesExceeded", st)
    put("cap3", body(timeLimitInSeconds=1))
    time.sleep(1.2)
    st = h("POST", f"{NW}/packetCaptures/cap3/queryStatus")["body"]
    ok("TimeExceeded stops the capture", st["packetCaptureStatus"] == "Stopped" and st["stopReason"] == "TimeExceeded", st)
    ok("empty capture still a valid pcap", any(len(b["data"]) == 24 for b in a.blob_store.blobs[key].values()))
    # netsim deltas (offline Docker path)
    put("cap4", body(filters=[{"protocol": "UDP"}]))
    n = pc.ingest_flows(a.state, [{"src": ip, "dst": "10.90.1.50", "proto": 17, "sport": 5353, "dport": 53, "packets": 4, "bytes": 400, "action": "ACCEPT"},
                                  {"src": ip, "dst": "10.90.1.50", "proto": 6, "sport": 1, "dport": 22, "packets": 4, "bytes": 400, "action": "ACCEPT"},
                                  {"src": ip, "dst": "10.90.1.51", "proto": 17, "sport": 5353, "dport": 53, "packets": 4, "bytes": 400, "action": "REJECT"}],
                        blob_store=a.blob_store, blob_mod=blob)
    ok("netsim ACCEPT deltas matching the UDP filter captured, REJECT never", n == 1, n)
    h("POST", f"{NW}/packetCaptures/cap4/stop")
    ok("filePath-only capture accepted", put("cap5", {"properties": {"target": VM, "storageLocation": {"filePath": "/var/captures/a.cap"}}})["status"] == 201)
    print("PASS")


if __name__ == "__main__":
    run()
