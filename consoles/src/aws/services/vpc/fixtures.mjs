/* UI-conformance fixtures for VPC (native EC2 Query protocol: form-encoded Action=..., XML
 * response). Standalone (no import from api.js / wire.js — those touch browser globals that
 * don't exist under the Node harness). See ec2/fixtures.mjs for the shared contract; each
 * fixture returns the resource's own generated ID, which the page then renders directly
 * (list column, detail-page breadcrumb) — same convention as ec2/dynamodb. */
function flatten(value, prefix = "", out = {}) {
  if (value === undefined || value === null || value === "") return out;
  if (Array.isArray(value)) value.forEach((v, i) => flatten(v, prefix ? `${prefix}.${i + 1}` : String(i + 1), out));
  else if (typeof value === "object") Object.entries(value).forEach(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k, out));
  else out[prefix] = value;
  return out;
}
const Q = (action, params = {}) => ({
  svc: "ec2",
  headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8" },
  body: new URLSearchParams(flatten({ Action: action, ...params })).toString(),
});
const xid = (xml, tag) => { const m = String(xml).match(new RegExp(`<${tag}>(.*?)</${tag}>`)); return m ? m[1] : null; };

async function vpcAndSubnet(wire, cidr = "10.77.0.0/16", subnetCidr = "10.77.1.0/24") {
  const vpcBody = await wire("POST", "/", Q("CreateVpc", { CidrBlock: cidr }));
  const vpcId = xid(vpcBody, "vpcId");
  const subBody = await wire("POST", "/", Q("CreateSubnet", { VpcId: vpcId, CidrBlock: subnetCidr }));
  return { vpcId, subnetId: xid(subBody, "subnetId") };
}

export default {
  "live-vpc": async (wire) => {
    const body = await wire("POST", "/", Q("CreateVpc", { CidrBlock: "10.78.0.0/16" }));
    return xid(body, "vpcId");
  },
  "live-subnet": async (wire) => {
    const { subnetId } = await vpcAndSubnet(wire, "10.79.0.0/16", "10.79.1.0/24");
    return subnetId;
  },
  "live-route-table": async (wire) => {
    const { vpcId } = await vpcAndSubnet(wire, "10.80.0.0/16", "10.80.1.0/24");
    const body = await wire("POST", "/", Q("CreateRouteTable", { VpcId: vpcId }));
    return xid(body, "routeTableId");
  },
  "live-igw": async (wire) => {
    const body = await wire("POST", "/", Q("CreateInternetGateway"));
    return xid(body, "internetGatewayId");
  },
  "live-nat-gateway": async (wire) => {
    const { subnetId } = await vpcAndSubnet(wire, "10.81.0.0/16", "10.81.1.0/24");
    const body = await wire("POST", "/", Q("CreateNatGateway", { SubnetId: subnetId }));
    return xid(body, "natGatewayId");
  },
  "live-nacl": async (wire) => {
    const { vpcId } = await vpcAndSubnet(wire, "10.85.0.0/16", "10.85.1.0/24");
    const body = await wire("POST", "/", Q("CreateNetworkAcl", { VpcId: vpcId }));
    return xid(body, "networkAclId");
  },
  "live-sg": async (wire, uniq) => {
    const body = await wire("POST", "/", Q("CreateSecurityGroup", { GroupName: uniq, GroupDescription: "v4 live security group (vpc)" }));
    return xid(body, "groupId");
  },
  "live-eip": async (wire) => {
    const body = await wire("POST", "/", Q("AllocateAddress"));
    return xid(body, "allocationId");
  },
  "live-egress-only-igw": async (wire) => {
    const { vpcId } = await vpcAndSubnet(wire, "10.82.0.0/16", "10.82.1.0/24");
    const body = await wire("POST", "/", Q("CreateEgressOnlyInternetGateway", { VpcId: vpcId }));
    return xid(body, "egressOnlyInternetGatewayId");
  },
  "live-dhcp-options": async (wire) => {
    const body = await wire("POST", "/", Q("CreateDhcpOptions", { "DhcpConfiguration.1.Key": "domain-name", "DhcpConfiguration.1.Value.1": "v4-live.internal" }));
    return xid(body, "dhcpOptionsId");
  },
  "live-prefix-list": async (wire, uniq) => {
    const body = await wire("POST", "/", Q("CreateManagedPrefixList", { PrefixListName: uniq, MaxEntries: 5 }));
    return uniq;
  },
  "live-peering-connection": async (wire) => {
    const a = await wire("POST", "/", Q("CreateVpc", { CidrBlock: "10.83.0.0/16" }));
    const b = await wire("POST", "/", Q("CreateVpc", { CidrBlock: "10.84.0.0/16" }));
    const body = await wire("POST", "/", Q("CreateVpcPeeringConnection", { VpcId: xid(a, "vpcId"), PeerVpcId: xid(b, "vpcId") }));
    return xid(body, "vpcPeeringConnectionId");
  },
  "live-route-server": async (wire) => {
    const body = await wire("POST", "/", Q("CreateRouteServer", { AmazonSideAsn: 65010 }));
    return xid(body, "routeServerId");
  },
  "live-insights-path": async (wire) => {
    const igw = await wire("POST", "/", Q("CreateInternetGateway"));
    const body = await wire("POST", "/", Q("CreateNetworkInsightsPath", {
      Source: xid(igw, "internetGatewayId"), DestinationIp: "203.0.113.5", Protocol: "tcp", DestinationPort: 443,
    }));
    return xid(body, "networkInsightsPathId");
  },
  "live-vpc-endpoint": async (wire) => {
    const { vpcId } = await vpcAndSubnet(wire, "10.86.0.0/16", "10.86.1.0/24");
    const rt = await wire("POST", "/", Q("CreateRouteTable", { VpcId: vpcId }));
    const body = await wire("POST", "/", Q("CreateVpcEndpoint", {
      VpcId: vpcId, ServiceName: "com.amazonaws.us-east-1.s3", VpcEndpointType: "Gateway", "RouteTableId.1": xid(rt, "routeTableId"),
    }));
    return xid(body, "vpcEndpointId");
  },
  "live-vpc-endpoint-service": async (wire) => {
    const body = await wire("POST", "/", Q("CreateVpcEndpointServiceConfiguration", {
      "NetworkLoadBalancerArn.1": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/uic-nlb/abc",
    }));
    return xid(body, "serviceId");
  },
  "live-access-scope": async (wire) => {
    const body = await wire("POST", "/", Q("CreateNetworkInsightsAccessScope"));
    return xid(body, "networkInsightsAccessScopeId");
  },
  "live-verified-access-instance": async (wire, uniq) => {
    const body = await wire("POST", "/", Q("CreateVerifiedAccessInstance", { Description: `uic-va-${uniq}` }));
    return xid(body, "verifiedAccessInstanceId");
  },
  "live-verified-access-group": async (wire, uniq) => {
    const inst = await wire("POST", "/", Q("CreateVerifiedAccessInstance", { Description: `uic-va-group-${uniq}` }));
    const body = await wire("POST", "/", Q("CreateVerifiedAccessGroup", { VerifiedAccessInstanceId: xid(inst, "verifiedAccessInstanceId"), Description: uniq }));
    return xid(body, "verifiedAccessGroupId");
  },
  "live-verified-access-trust-provider": async (wire, uniq) => {
    const body = await wire("POST", "/", Q("CreateVerifiedAccessTrustProvider", { TrustProviderType: "user", PolicyReferenceName: `uic-${uniq}` }));
    return xid(body, "verifiedAccessTrustProviderId");
  },
  "live-verified-access-endpoint": async (wire, uniq) => {
    const inst = await wire("POST", "/", Q("CreateVerifiedAccessInstance", { Description: `uic-va-ep-${uniq}` }));
    const grp = await wire("POST", "/", Q("CreateVerifiedAccessGroup", { VerifiedAccessInstanceId: xid(inst, "verifiedAccessInstanceId") }));
    const body = await wire("POST", "/", Q("CreateVerifiedAccessEndpoint", { VerifiedAccessGroupId: xid(grp, "verifiedAccessGroupId"), ApplicationDomain: `${uniq}.internal` }));
    return xid(body, "verifiedAccessEndpointId");
  },
};
