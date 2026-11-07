"""REAL azure-mgmt-network (packet_captures + verify_ip_flow) and azure-storage-blob against the Azure wire, endpoint changed only: a packet
capture is created/started through the SDK, flows the shared evaluator allows are captured, the SDK stops it and reads status, and the
.cap file is downloaded back from network-watcher-logs through azure-storage-blob and parsed as libpcap.
Run: PYTHONPATH=. <venv>/bin/python tests/conformance/test_azure_pcap_sdk.py   (or pytest)"""
import struct
import time
import uuid

import requests
from azure.core.credentials import AccessToken, AzureNamedKeyCredential
from azure.core.pipeline.policies import SansIOHTTPPolicy
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network import models as nm
from azure.storage.blob import BlobServiceClient

from tests.conformance import _azure_http

SUB = "00000000-0000-0000-0000-cloudlearn01"
BASE, ROUTER = _azure_http.start()
ROUTER.az_arm.blob_store = ROUTER.az_blob      # what nano_registry / the appliance do for the router's ARM store
SFX = uuid.uuid4().hex[:6]
RG = f"rg-pc-{SFX}"
ACCT = "pcsdk" + SFX


class _Cred:
    def get_token(self, *a, **k):
        return AccessToken("t", int(time.time()) + 3600)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def rest(method, path, body=None, v="2023-11-01"):
    r = requests.request(method, BASE + path, json=body, params={"api-version": v}, timeout=30)
    assert r.status_code < 300, (method, path, r.status_code, r.text)
    return r.json() if r.text else {}


def test_packet_capture_sdk():
    base = f"/subscriptions/{SUB}/resourceGroups/{RG}"
    rest("PUT", base, {"location": "eastus"}, "2021-04-01")
    rest("PUT", f"{base}/providers/Microsoft.Storage/storageAccounts/{ACCT}", {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}}, "2023-01-01")
    nsg = rest("PUT", f"{base}/providers/Microsoft.Network/networkSecurityGroups/nsg", {"location": "eastus", "properties": {}})
    rest("PUT", f"{base}/providers/Microsoft.Network/virtualNetworks/vn", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "subnets": [
        {"name": "s", "properties": {"addressPrefix": "10.0.1.0/24", "networkSecurityGroup": {"id": nsg["id"]}}}]}})
    nic = rest("PUT", f"{base}/providers/Microsoft.Network/networkInterfaces/nic", {"location": "eastus", "properties": {"ipConfigurations": [
        {"name": "c", "properties": {"subnet": {"id": f"{base}/providers/Microsoft.Network/virtualNetworks/vn/subnets/s"}}}]}})
    ip = nic["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"]
    vm = rest("PUT", f"{base}/providers/Microsoft.Compute/virtualMachines/vm", {"location": "eastus", "properties": {"networkProfile": {"networkInterfaces": [{"id": nic["id"]}]}}}, "2023-09-01")
    net = NetworkManagementClient(_Cred(), SUB, base_url=BASE, authentication_policy=SansIOHTTPPolicy())
    net.network_watchers.create_or_update(RG, "nw", {"location": "eastus"})
    st_id = f"{base}/providers/Microsoft.Storage/storageAccounts/{ACCT}"

    cap = net.packet_captures.begin_create(RG, "nw", "sdkcap", nm.PacketCapture(target=vm["id"], storage_location=nm.PacketCaptureStorageLocation(storage_id=st_id),
                                                               filters=[nm.PacketCaptureFilter(protocol="TCP", remote_ip_address="203.0.113.0/24", remote_port="443")])).result()
    ok("SDK create returns the capture", cap.name == "sdkcap" and cap.target == vm["id"] and cap.time_limit_in_seconds == 18000, cap)
    ok("SDK get/list", net.packet_captures.get(RG, "nw", "sdkcap").name == "sdkcap" and [c.name for c in net.packet_captures.list(RG, "nw")] == ["sdkcap"])
    s = net.packet_captures.begin_get_status(RG, "nw", "sdkcap").result()
    ok("SDK get_status Running", s.packet_capture_status == "Running", s)
    for port in (443, 80):
        r = net.network_watchers.begin_verify_ip_flow(RG, "nw", nm.VerificationIPFlowParameters(target_resource_id=vm["id"], direction="Outbound", protocol="TCP", local_port="50000",
                                                               remote_port=str(port), local_ip_address=ip, remote_ip_address="203.0.113.9")).result()
        ok(f"verify_ip_flow :{port} Allow", r.access == "Allow")
    net.packet_captures.begin_stop(RG, "nw", "sdkcap").result()
    s = net.packet_captures.begin_get_status(RG, "nw", "sdkcap").result()
    ok("SDK status Stopped/Manual", s.packet_capture_status == "Stopped" and s.stop_reason == "Manual", s)

    key = "a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2V5a2U="
    svc = BlobServiceClient(f"{BASE}/{ACCT}", credential=AzureNamedKeyCredential(ACCT, key))
    blobs = list(svc.get_container_client("network-watcher-logs").list_blobs())
    ok("one .cap blob in network-watcher-logs", len(blobs) == 1 and blobs[0].name.endswith(".cap") and "/virtualmachines/vm/" in blobs[0].name, [b.name for b in blobs])
    data = svc.get_blob_client("network-watcher-logs", blobs[0].name).download_blob().readall()
    magic, _, _, _, _, _, link = struct.unpack("<IHHiIII", data[:24])
    caplen = struct.unpack("<IIII", data[24:40])[2]
    fr = data[40:40 + caplen]
    ok("downloaded file is libpcap with the one filtered flow (VM -> 203.0.113.9:443)", magic == 0xA1B2C3D4 and link == 1 and len(data) == 40 + caplen
       and fr[30:34] == bytes([203, 0, 113, 9]) and struct.unpack("!H", fr[36:38])[0] == 443)
    net.packet_captures.begin_delete(RG, "nw", "sdkcap").result()
    ok("SDK delete", list(net.packet_captures.list(RG, "nw")) == [])


if __name__ == "__main__":
    test_packet_capture_sdk()
    print("PASS")
