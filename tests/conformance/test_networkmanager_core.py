"""AWS Network Manager inventory control plane via AwsWireRouter: global networks, sites, devices, links, link associations, transit gateway
registrations (against real transit gateways in the EC2 model), tags and the real dependency errors.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_networkmanager_core.py
"""
import json
from urllib.parse import quote, urlencode

from core.aws_wire_router import AwsWireRouter

NM = "AWS4-HMAC-SHA256 Credential=T/20261105/us-west-2/networkmanager/aws4_request, SignedHeaders=host, Signature=0"
EC2 = "AWS4-HMAC-SHA256 Credential=T/20261105/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def nm(r, method, path, body=None, query=None):
    o = r.handle(method, path, query or {}, {"authorization": NM, "content-type": "application/json"}, json.dumps(body or {}).encode() if method != "GET" else b"")
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def main():
    r = AwsWireRouter()
    s, o = nm(r, "POST", "/global-networks", {"Description": "corp WAN", "Tags": [{"Key": "env", "Value": "prod"}]})
    gn = o["GlobalNetwork"]["GlobalNetworkId"]
    _check("create global network", s == 200 and gn.startswith("global-network-") and o["GlobalNetwork"]["GlobalNetworkArn"].endswith(":global-network/" + gn) and o["GlobalNetwork"]["State"] == "AVAILABLE")
    _check("reserved tag key refused", nm(r, "POST", "/global-networks", {"Tags": [{"Key": "aws:x", "Value": "1"}]})[0] == 400)
    s, o = nm(r, "GET", "/global-networks")
    _check("describe global networks", [g["GlobalNetworkId"] for g in o["GlobalNetworks"]] == [gn])
    _check("unknown global network", nm(r, "GET", "/global-networks/global-network-nope/sites")[0] == 404)

    s, o = nm(r, "POST", f"/global-networks/{gn}/sites", {"Description": "HQ", "Location": {"Address": "1 Main St", "Latitude": "47.6", "Longitude": "-122.3"}})
    site = o["Site"]["SiteId"]
    _check("create site", s == 200 and site.startswith("site-") and o["Site"]["Location"]["Latitude"] == "47.6")
    _check("latitude out of range", nm(r, "POST", f"/global-networks/{gn}/sites", {"Location": {"Latitude": "123"}})[0] == 400)
    s, o = nm(r, "POST", f"/global-networks/{gn}/devices", {"SiteId": site, "Description": "edge router", "Type": "router", "Vendor": "Acme", "Model": "R1"})
    dev = o["Device"]["DeviceId"]
    _check("create device", s == 200 and dev.startswith("device-") and o["Device"]["SiteId"] == site)
    _check("device in unknown site", nm(r, "POST", f"/global-networks/{gn}/devices", {"SiteId": "site-nope"})[0] == 404)
    _check("link needs bandwidth", nm(r, "POST", f"/global-networks/{gn}/links", {"SiteId": site})[0] == 400)
    s, o = nm(r, "POST", f"/global-networks/{gn}/links", {"SiteId": site, "Bandwidth": {"UploadSpeed": 100, "DownloadSpeed": 200}, "Provider": "ISP", "Type": "broadband"})
    link = o["Link"]["LinkId"]
    _check("create link", s == 200 and o["Link"]["Bandwidth"] == {"UploadSpeed": 100, "DownloadSpeed": 200})
    s, o = nm(r, "POST", f"/global-networks/{gn}/link-associations", {"DeviceId": dev, "LinkId": link})
    _check("associate link", s == 200 and o["LinkAssociation"]["LinkAssociationState"] == "AVAILABLE")
    _check("duplicate association", nm(r, "POST", f"/global-networks/{gn}/link-associations", {"DeviceId": dev, "LinkId": link})[0] == 409)
    _check("get associations", len(nm(r, "GET", f"/global-networks/{gn}/link-associations", query={"deviceId": dev})[1]["LinkAssociations"]) == 1)
    _check("device with associations not deletable", nm(r, "DELETE", f"/global-networks/{gn}/devices/{dev}")[0] == 409)
    _check("site with devices not deletable", nm(r, "DELETE", f"/global-networks/{gn}/sites/{site}")[0] == 409)

    # transit gateway registration against the real EC2 model
    o = r.handle("POST", "/", {}, {"authorization": EC2, "content-type": "application/x-www-form-urlencoded"}, urlencode({"Action": "CreateTransitGateway", "Version": "2016-11-15"}).encode())
    import re
    tgw = re.search(r"<transitGatewayId>(tgw-[0-9a-f]+)</transitGatewayId>", o["body"].decode()).group(1)
    arn = f"arn:aws:ec2:us-east-1:123456789012:transit-gateway/{tgw}"
    _check("registering a transit gateway that does not exist", nm(r, "POST", f"/global-networks/{gn}/transit-gateway-registrations", {"TransitGatewayArn": "arn:aws:ec2:us-east-1:123456789012:transit-gateway/tgw-0123456789abcdef0"})[0] == 404)
    _check("malformed ARN", nm(r, "POST", f"/global-networks/{gn}/transit-gateway-registrations", {"TransitGatewayArn": "tgw-1"})[0] == 400)
    s, o = nm(r, "POST", f"/global-networks/{gn}/transit-gateway-registrations", {"TransitGatewayArn": arn})
    _check("register transit gateway", s == 200 and o["TransitGatewayRegistration"]["State"]["Code"] == "AVAILABLE")
    _check("duplicate registration", nm(r, "POST", f"/global-networks/{gn}/transit-gateway-registrations", {"TransitGatewayArn": arn})[0] == 409)
    s, o2 = nm(r, "POST", "/global-networks", {})
    gn2 = o2["GlobalNetwork"]["GlobalNetworkId"]
    s, o = nm(r, "POST", f"/global-networks/{gn2}/transit-gateway-registrations", {"TransitGatewayArn": arn})
    _check("a TGW registers to ONE global network", s == 409 and gn in o["message"])
    _check("get registrations", len(nm(r, "GET", f"/global-networks/{gn}/transit-gateway-registrations")[1]["TransitGatewayRegistrations"]) == 1)
    _check("global network with TGW not deletable", nm(r, "DELETE", f"/global-networks/{gn}")[0] == 409)

    # tags
    dev_arn = f"arn:aws:networkmanager::123456789012:device/{gn}/{dev}"
    nm(r, "POST", "/tags/" + quote(dev_arn, safe=""), {"Tags": [{"Key": "role", "Value": "edge"}]})
    s, o = nm(r, "GET", "/tags/" + quote(dev_arn, safe=""))
    _check("tags round-trip", o["TagList"] == [{"Key": "role", "Value": "edge"}])
    nm(r, "DELETE", "/tags/" + quote(dev_arn, safe=""), query={"tagKeys": "role"})
    _check("untag", nm(r, "GET", "/tags/" + quote(dev_arn, safe=""))[1]["TagList"] == [])

    # teardown in dependency order
    _check("disassociate", nm(r, "DELETE", f"/global-networks/{gn}/link-associations", query={"deviceId": dev, "linkId": link})[0] == 200)
    _check("delete device", nm(r, "DELETE", f"/global-networks/{gn}/devices/{dev}")[0] == 200)
    _check("delete link", nm(r, "DELETE", f"/global-networks/{gn}/links/{link}")[0] == 200)
    _check("delete site", nm(r, "DELETE", f"/global-networks/{gn}/sites/{site}")[0] == 200)
    _check("deregister TGW", nm(r, "DELETE", f"/global-networks/{gn}/transit-gateway-registrations/{quote(arn, safe='')}")[0] == 200)
    _check("delete global network", nm(r, "DELETE", f"/global-networks/{gn}")[0] == 200)
    _check("now the TGW can register elsewhere", nm(r, "POST", f"/global-networks/{gn2}/transit-gateway-registrations", {"TransitGatewayArn": arn})[0] == 200)
    print("networkmanager: all ok")


if __name__ == "__main__":
    main()
