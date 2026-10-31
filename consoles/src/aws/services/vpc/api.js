/* VPC over the native EC2 Query protocol (form-encoded Action=.../XML responses).
 * EC2 and VPC share one AWS service ("ec2" credential scope) and one backend
 * core (core/vpc_core.py) — see ../ec2/api.js for the compute/storage resource surface. */
import { awsQuery, asList } from "../../../common/wire.js";

/** Flatten a JS object/array into the Query wire's dotted-index form (see ../ec2/api.js). */
function flatten(value, prefix = "", out = {}) {
  if (value === undefined || value === null || value === "") return out;
  if (Array.isArray(value)) value.forEach((v, i) => flatten(v, prefix ? `${prefix}.${i + 1}` : String(i + 1), out));
  else if (typeof value === "object") Object.entries(value).forEach(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k, out));
  else out[prefix] = value;
  return out;
}

const call = (action, params = {}) => awsQuery("ec2", action, flatten(params)).then((r) => r[`${action}Response`] || {});

export const tagsFromXml = (x) => Object.fromEntries(asList(x?.item).map((t) => [t.key, t.value || ""]));
export const tagsToArray = (tags) => Object.entries(tags || {}).filter(([k]) => k).map(([Key, Value]) => ({ Key, Value }));
export const tagSpec = (resourceType, tags) => (Object.keys(tags || {}).length ? [{ ResourceType: resourceType, Tag: tagsToArray(tags) }] : undefined);
export const createTags = (resourceIds, tags) => call("CreateTags", { ResourceId: resourceIds, Tag: tagsToArray(tags) });
export const deleteTags = (resourceIds, tagKeys) => call("DeleteTags", { ResourceId: resourceIds, Tag: (tagKeys || []).map((Key) => ({ Key })) });

// ── VPCs ──────────────────────────────────────────────────────────────────
const vpcFromXml = (x) => ({
  VpcId: x.vpcId, CidrBlock: x.cidrBlock, State: x.state, InstanceTenancy: x.instanceTenancy,
  DhcpOptionsId: x.dhcpOptionsId, IsDefault: x.isDefault === "true",
  MainRouteTableId: x.mainRouteTableId, MainNetworkAclId: x.mainNetworkAclId,
  OwnerId: x.ownerId, Tags: tagsFromXml(x.tagSet),
});
export async function describeVpcs(filter = {}) {
  const r = await call("DescribeVpcs", filter);
  return asList(r.vpcSet?.item).map(vpcFromXml);
}
export const describeVpc = (id) => describeVpcs({ VpcId: [id] }).then((xs) => xs[0]);
export const createVpc = (cidrBlock, tags, tenancy) => call("CreateVpc", { CidrBlock: cidrBlock, InstanceTenancy: tenancy, TagSpecification: tagSpec("vpc", tags) }).then((r) => vpcFromXml(r.vpc));
export const deleteVpc = (id) => call("DeleteVpc", { VpcId: id });
export const modifyVpcAttribute = (id, attr) => call("ModifyVpcAttribute", { VpcId: id, ...attr });
export async function describeVpcAttribute(id, attribute) {
  const r = await call("DescribeVpcAttribute", { VpcId: id, Attribute: attribute });
  const tag = attribute === "enableDnsHostnames" ? "enableDnsHostnames" : "enableDnsSupport";
  return r[tag]?.value === "true";
}

// ── subnets ───────────────────────────────────────────────────────────────
const subnetFromXml = (x) => ({
  SubnetId: x.subnetId, VpcId: x.vpcId, CidrBlock: x.cidrBlock, AvailabilityZone: x.availabilityZone,
  State: x.state, DefaultForAz: x.defaultForAz === "true", MapPublicIpOnLaunch: x.mapPublicIpOnLaunch === "true",
  AvailableIpAddressCount: Number(x.availableIpAddressCount || 0), RouteTableId: x.routeTableId || "",
  NetworkAclId: x.networkAclId || "", OwnerId: x.ownerId, Tags: tagsFromXml(x.tagSet),
});
export async function describeSubnets(filter = {}) {
  const r = await call("DescribeSubnets", filter);
  return asList(r.subnetSet?.item).map(subnetFromXml);
}
export const describeSubnet = (id) => describeSubnets({ SubnetId: [id] }).then((xs) => xs[0]);
export const createSubnet = (vpcId, cidrBlock, az, tags) => call("CreateSubnet", { VpcId: vpcId, CidrBlock: cidrBlock, AvailabilityZone: az, TagSpecification: tagSpec("subnet", tags) }).then((r) => subnetFromXml(r.subnet));
export const deleteSubnet = (id) => call("DeleteSubnet", { SubnetId: id });

// ── route tables ────────────────────────────────────────────────────────
const routeFromXml = (x) => ({ DestinationCidrBlock: x.destinationCidrBlock, GatewayId: x.gatewayId, State: x.state });
const rtAssocFromXml = (x) => ({ RouteTableAssociationId: x.routeTableAssociationId, RouteTableId: x.routeTableId, SubnetId: x.subnetId, Main: x.main === "true" });
const rtFromXml = (x) => ({
  RouteTableId: x.routeTableId, VpcId: x.vpcId, Tags: tagsFromXml(x.tagSet),
  Routes: asList(x.routeSet?.item).map(routeFromXml), Associations: asList(x.associationSet?.item).map(rtAssocFromXml),
});
export async function describeRouteTables(filter = {}) {
  const r = await call("DescribeRouteTables", filter);
  return asList(r.routeTableSet?.item).map(rtFromXml);
}
export const describeRouteTable = (id) => describeRouteTables({ RouteTableId: [id] }).then((xs) => xs[0]);
export const createRouteTable = (vpcId, tags) => call("CreateRouteTable", { VpcId: vpcId, TagSpecification: tagSpec("route-table", tags) }).then((r) => rtFromXml(r.routeTable));
export const deleteRouteTable = (id) => call("DeleteRouteTable", { RouteTableId: id });
export const createRoute = (routeTableId, destinationCidrBlock, gatewayId) => call("CreateRoute", { RouteTableId: routeTableId, DestinationCidrBlock: destinationCidrBlock, GatewayId: gatewayId });
export const deleteRoute = (routeTableId, destinationCidrBlock) => call("DeleteRoute", { RouteTableId: routeTableId, DestinationCidrBlock: destinationCidrBlock });
export const associateRouteTable = (routeTableId, subnetId) => call("AssociateRouteTable", { RouteTableId: routeTableId, SubnetId: subnetId }).then((r) => r.associationId);
export const disassociateRouteTable = (associationId) => call("DisassociateRouteTable", { AssociationId: associationId });
export const replaceRouteTableAssociation = (associationId, routeTableId) => call("ReplaceRouteTableAssociation", { AssociationId: associationId, RouteTableId: routeTableId }).then((r) => r.newAssociationId);

// ── internet gateways ──────────────────────────────────────────────────
const igwFromXml = (x) => ({
  InternetGatewayId: x.internetGatewayId, Tags: tagsFromXml(x.tagSet),
  Attachments: asList(x.attachmentSet?.item).map((a) => ({ VpcId: a.vpcId, State: a.state })),
});
export async function describeInternetGateways(filter = {}) {
  const r = await call("DescribeInternetGateways", filter);
  return asList(r.internetGatewaySet?.item).map(igwFromXml);
}
export const describeInternetGateway = (id) => describeInternetGateways({ InternetGatewayId: [id] }).then((xs) => xs[0]);
export const createInternetGateway = (tags) => call("CreateInternetGateway", { TagSpecification: tagSpec("internet-gateway", tags) }).then((r) => igwFromXml(r.internetGateway));
export const attachInternetGateway = (igwId, vpcId) => call("AttachInternetGateway", { InternetGatewayId: igwId, VpcId: vpcId });
export const detachInternetGateway = (igwId, vpcId) => call("DetachInternetGateway", { InternetGatewayId: igwId, VpcId: vpcId });
export const deleteInternetGateway = (id) => call("DeleteInternetGateway", { InternetGatewayId: id });

// ── NAT gateways ────────────────────────────────────────────────────────
const natAddrFromXml = (x) => ({ AllocationId: x.allocationId, PublicIp: x.publicIp, PrivateIp: x.privateIp, NetworkInterfaceId: x.networkInterfaceId });
const natFromXml = (x) => ({
  NatGatewayId: x.natGatewayId, VpcId: x.vpcId, SubnetId: x.subnetId, State: x.state,
  ConnectivityType: x.connectivityType, CreateTime: x.createTime, Tags: tagsFromXml(x.tagSet),
  NatGatewayAddresses: asList(x.natGatewayAddressSet?.item).map(natAddrFromXml),
});
export async function describeNatGateways(filter = {}) {
  const r = await call("DescribeNatGateways", filter);
  return asList(r.natGatewaySet?.item).map(natFromXml);
}
export const describeNatGateway = (id) => describeNatGateways({ NatGatewayId: [id] }).then((xs) => xs[0]);
export const createNatGateway = (subnetId, connectivityType, tags, allocationId) => call("CreateNatGateway", { SubnetId: subnetId, ConnectivityType: connectivityType, AllocationId: allocationId, TagSpecification: tagSpec("natgateway", tags) }).then((r) => natFromXml(r.natGateway));
export const deleteNatGateway = (id) => call("DeleteNatGateway", { NatGatewayId: id });

// ── network ACLs ────────────────────────────────────────────────────────
const naclEntryFromXml = (x) => ({
  RuleNumber: Number(x.ruleNumber), Protocol: x.protocol, RuleAction: x.ruleAction, Egress: x.egress === "true",
  CidrBlock: x.cidrBlock, PortRange: x.portRange ? { From: Number(x.portRange.from), To: Number(x.portRange.to) } : undefined,
});
const naclAssocFromXml = (x) => ({ NetworkAclAssociationId: x.networkAclAssociationId, NetworkAclId: x.networkAclId, SubnetId: x.subnetId });
const naclFromXml = (x) => ({
  NetworkAclId: x.networkAclId, VpcId: x.vpcId, IsDefault: x.default === "true", Tags: tagsFromXml(x.tagSet),
  Entries: asList(x.entrySet?.item).map(naclEntryFromXml), Associations: asList(x.associationSet?.item).map(naclAssocFromXml),
});
export async function describeNetworkAcls(filter = {}) {
  const r = await call("DescribeNetworkAcls", filter);
  return asList(r.networkAclSet?.item).map(naclFromXml);
}
export const describeNetworkAcl = (id) => describeNetworkAcls({ NetworkAclId: [id] }).then((xs) => xs[0]);
export const createNetworkAcl = (vpcId, tags) => call("CreateNetworkAcl", { VpcId: vpcId, TagSpecification: tagSpec("network-acl", tags) }).then((r) => naclFromXml(r.networkAcl));
export const deleteNetworkAcl = (id) => call("DeleteNetworkAcl", { NetworkAclId: id });
export const createNetworkAclEntry = (networkAclId, entry) => call("CreateNetworkAclEntry", {
  NetworkAclId: networkAclId, RuleNumber: entry.RuleNumber, Protocol: entry.Protocol, RuleAction: entry.RuleAction,
  Egress: entry.Egress, CidrBlock: entry.CidrBlock, "PortRange.From": entry.PortRange?.From, "PortRange.To": entry.PortRange?.To,
});
export const deleteNetworkAclEntry = (networkAclId, ruleNumber, egress) => call("DeleteNetworkAclEntry", { NetworkAclId: networkAclId, RuleNumber: ruleNumber, Egress: egress });
export const associateNetworkAcl = (networkAclId, subnetId) => call("AssociateNetworkAcl", { NetworkAclId: networkAclId, SubnetId: subnetId });
export const replaceNetworkAclAssociation = (associationId, networkAclId) => call("ReplaceNetworkAclAssociation", { AssociationId: associationId, NetworkAclId: networkAclId }).then((r) => r.newAssociationId);

// ── security groups (shared with the EC2 console — same resource) ───────
export const permFromXml = (x) => ({
  IpProtocol: x.ipProtocol, FromPort: x.fromPort !== undefined && x.fromPort !== "" ? Number(x.fromPort) : undefined,
  ToPort: x.toPort !== undefined && x.toPort !== "" ? Number(x.toPort) : undefined,
  cidrs: asList(x.ipRanges?.item).map((r) => r.cidrIp), groupIds: asList(x.groups?.item).map((g) => g.groupId),
  RuleId: x.securityGroupRuleId, Description: x.description,
});
const sgFromXml = (x) => ({
  GroupId: x.groupId, GroupName: x.groupName, GroupDescription: x.groupDescription, VpcId: x.vpcId,
  Tags: tagsFromXml(x.tagSet), IpPermissions: asList(x.ipPermissions?.item).map(permFromXml), IpPermissionsEgress: asList(x.ipPermissionsEgress?.item).map(permFromXml),
});
export const createSecurityGroup = (name, description, vpcId, tags) => call("CreateSecurityGroup", { GroupName: name, GroupDescription: description, VpcId: vpcId, TagSpecification: tagSpec("security-group", tags) }).then((r) => r.groupId);
export async function describeSecurityGroups(filter = {}) {
  const r = await call("DescribeSecurityGroups", filter);
  return asList(r.securityGroupInfo?.item).map(sgFromXml);
}
export const describeSecurityGroup = (id) => describeSecurityGroups({ GroupId: [id] }).then((xs) => xs[0]);
export const deleteSecurityGroup = (id) => call("DeleteSecurityGroup", { GroupId: id });
const permParams = (perms) => ({
  IpPermissions: perms.map((p) => ({ IpProtocol: p.IpProtocol, FromPort: p.FromPort, ToPort: p.ToPort, IpRanges: p.cidr ? [{ CidrIp: p.cidr, Description: p.description }] : undefined, Groups: p.groupId ? [{ GroupId: p.groupId }] : undefined })),
});
export const authorizeIngress = (groupId, perms) => call("AuthorizeSecurityGroupIngress", { GroupId: groupId, ...permParams(perms) });
export const authorizeEgress = (groupId, perms) => call("AuthorizeSecurityGroupEgress", { GroupId: groupId, ...permParams(perms) });
export const revokeIngress = (groupId, ruleIds) => call("RevokeSecurityGroupIngress", { GroupId: groupId, SecurityGroupRuleId: ruleIds });
export const revokeEgress = (groupId, ruleIds) => call("RevokeSecurityGroupEgress", { GroupId: groupId, SecurityGroupRuleId: ruleIds });

// ── elastic IPs ───────────────────────────────────────────────────────────
const addressFromXml = (x) => ({
  PublicIp: x.publicIp, AllocationId: x.allocationId, Domain: x.domain, InstanceId: x.instanceId,
  AssociationId: x.associationId, NetworkInterfaceId: x.networkInterfaceId, PrivateIpAddress: x.privateIpAddress,
  NetworkBorderGroup: x.networkBorderGroup, Tags: tagsFromXml(x.tagSet),
});
export const allocateAddress = (tags) => call("AllocateAddress", { TagSpecification: tagSpec("elastic-ip", tags) }).then(addressFromXml);
export async function describeAddresses() {
  const r = await call("DescribeAddresses");
  return asList(r.addressesSet?.item).map(addressFromXml);
}
export const associateAddress = (allocationId, instanceId) => call("AssociateAddress", { AllocationId: allocationId, InstanceId: instanceId });
export const disassociateAddress = (associationId) => call("DisassociateAddress", { AssociationId: associationId });
export const releaseAddress = (allocationId) => call("ReleaseAddress", { AllocationId: allocationId });

// ── egress-only internet gateways ─────────────────────────────────────────
const eigwFromXml = (x) => ({
  EgressOnlyInternetGatewayId: x.egressOnlyInternetGatewayId, Tags: tagsFromXml(x.tagSet),
  Attachments: asList(x.attachmentSet?.item).map((a) => ({ VpcId: a.vpcId, State: a.state })),
});
export const createEgressOnlyInternetGateway = (vpcId, tags) => call("CreateEgressOnlyInternetGateway", { VpcId: vpcId, TagSpecification: tagSpec("egress-only-internet-gateway", tags) }).then((r) => eigwFromXml(r.egressOnlyInternetGateway));
export async function describeEgressOnlyInternetGateways() {
  const r = await call("DescribeEgressOnlyInternetGateways");
  return asList(r.egressOnlyInternetGatewaySet?.item).map(eigwFromXml);
}
export const deleteEgressOnlyInternetGateway = (id) => call("DeleteEgressOnlyInternetGateway", { EgressOnlyInternetGatewayId: id });

// ── DHCP option sets ───────────────────────────────────────────────────────
const dhcpConfigFromXml = (x) => ({ Key: x.key, Values: asList(x.valueSet?.item).map((v) => v.value) });
const dhcpOptionsFromXml = (x) => ({
  DhcpOptionsId: x.dhcpOptionsId, Tags: tagsFromXml(x.tagSet),
  DhcpConfigurations: asList(x.dhcpConfigurationSet?.item).map(dhcpConfigFromXml),
});
export const createDhcpOptions = (configurations, tags) => call("CreateDhcpOptions", {
  DhcpConfiguration: configurations.map((c) => ({ Key: c.Key, Value: c.Values })), TagSpecification: tagSpec("dhcp-options", tags),
}).then((r) => dhcpOptionsFromXml(r.dhcpOptions));
export async function describeDhcpOptions() {
  const r = await call("DescribeDhcpOptions");
  return asList(r.dhcpOptionsSet?.item).map(dhcpOptionsFromXml);
}
export const deleteDhcpOptions = (id) => call("DeleteDhcpOptions", { DhcpOptionsId: id });
export const associateDhcpOptions = (vpcId, dhcpOptionsId) => call("AssociateDhcpOptions", { VpcId: vpcId, DhcpOptionsId: dhcpOptionsId });

// ── managed prefix lists ────────────────────────────────────────────────
const plFromXml = (x) => ({
  PrefixListId: x.prefixListId, PrefixListName: x.prefixListName, AddressFamily: x.addressFamily,
  MaxEntries: Number(x.maxEntries), State: x.state, OwnerId: x.ownerId, Version: Number(x.version), Tags: tagsFromXml(x.tagSet),
});
export const createManagedPrefixList = (name, maxEntries, addressFamily, entries, tags) => call("CreateManagedPrefixList", {
  PrefixListName: name, MaxEntries: maxEntries, AddressFamily: addressFamily,
  Entry: (entries || []).map((e) => ({ Cidr: e.Cidr, Description: e.Description })), TagSpecification: tagSpec("prefix-list", tags),
}).then((r) => plFromXml(r.prefixList));
export async function describeManagedPrefixLists() {
  const r = await call("DescribeManagedPrefixLists");
  return asList(r.prefixListSet?.item).map(plFromXml);
}
export const deleteManagedPrefixList = (id) => call("DeleteManagedPrefixList", { PrefixListId: id });

// ── VPC peering connections ────────────────────────────────────────────
const pcxFromXml = (x) => ({
  VpcPeeringConnectionId: x.vpcPeeringConnectionId, RequesterVpcId: x.requesterVpcInfo?.vpcId,
  AccepterVpcId: x.accepterVpcInfo?.vpcId, Status: x.status?.code, Tags: tagsFromXml(x.tagSet),
});
export const createVpcPeeringConnection = (vpcId, peerVpcId, tags) => call("CreateVpcPeeringConnection", { VpcId: vpcId, PeerVpcId: peerVpcId, TagSpecification: tagSpec("vpc-peering-connection", tags) }).then((r) => pcxFromXml(r.vpcPeeringConnection));
export async function describeVpcPeeringConnections() {
  const r = await call("DescribeVpcPeeringConnections");
  return asList(r.vpcPeeringConnectionSet?.item).map(pcxFromXml);
}
export const acceptVpcPeeringConnection = (id) => call("AcceptVpcPeeringConnection", { VpcPeeringConnectionId: id }).then((r) => pcxFromXml(r.vpcPeeringConnection));
export const deleteVpcPeeringConnection = (id) => call("DeleteVpcPeeringConnection", { VpcPeeringConnectionId: id });

// ── VPC route servers ───────────────────────────────────────────────────
const rsFromXml = (x) => ({ RouteServerId: x.routeServerId, AmazonSideAsn: Number(x.amazonSideAsn), State: x.state, Tags: tagsFromXml(x.tagSet) });
export const createRouteServer = (asn, tags) => call("CreateRouteServer", { AmazonSideAsn: asn, TagSpecification: tagSpec("route-server", tags) }).then((r) => rsFromXml(r.routeServer));
export async function describeRouteServers() {
  const r = await call("DescribeRouteServers");
  return asList(r.routeServerSet?.item).map(rsFromXml);
}
export const deleteRouteServer = (id) => call("DeleteRouteServer", { RouteServerId: id });

// ── reachability analyzer ──────────────────────────────────────────────
export async function analyzeReachability(source, destination, port, protocol = "tcp") {
  const params = { DestinationPort: port, Protocol: protocol };
  if (source.ip) params["Source.Ip"] = source.ip;
  (source.securityGroupIds || []).forEach((id, i) => { params[`Source.SecurityGroupId.${i + 1}`] = id; });
  if (destination.ip) params["Destination.Ip"] = destination.ip;
  (destination.securityGroupIds || []).forEach((id, i) => { params[`Destination.SecurityGroupId.${i + 1}`] = id; });
  const r = await call("AnalyzeReachability", params);
  return { reachable: r.reachable === "true", reason: r.reason, path: asList(r.path?.item) };
}

// ── VPC/subnet flow logs ───────────────────────────────────────────────
const flowLogFromXml = (x) => ({
  FlowLogId: x.flowLogId, FlowLogStatus: x.flowLogStatus, CreationTime: x.creationTime, ResourceId: x.resourceId,
  TrafficType: x.trafficType, LogDestinationType: x.logDestinationType, LogGroupName: x.logGroupName || "",
  LogDestination: x.logDestination || "", LogFormat: x.logFormat, DeliverLogsStatus: x.deliverLogsStatus,
  DeliverLogsPermissionArn: x.deliverLogsPermissionArn || "", MaxAggregationInterval: Number(x.maxAggregationInterval),
  Tags: tagsFromXml(x.tagSet),
});
export async function describeFlowLogs() {
  const r = await call("DescribeFlowLogs");
  return asList(r.flowLogSet?.item).map(flowLogFromXml);
}
export async function createFlowLog(resourceId, resourceType, opts = {}) {
  const r = await call("CreateFlowLogs", {
    ResourceId: [resourceId], ResourceType: resourceType, TrafficType: opts.trafficType || "ALL",
    LogDestinationType: opts.logDestinationType || "cloud-watch-logs", LogGroupName: opts.logGroupName,
    LogDestination: opts.logDestination, DeliverLogsPermissionArn: opts.deliverLogsPermissionArn,
    MaxAggregationInterval: opts.maxAggregationInterval || 600, TagSpecification: tagSpec("vpc-flow-log", opts.tags),
  });
  return asList(r.flowLogIdSet?.item)[0];
}
export const deleteFlowLogs = (ids) => call("DeleteFlowLogs", { FlowLogId: ids });

// ── Reachability Analyzer (Network Insights paths + analyses) ─────────────
const nipFromXml = (x) => ({
  NetworkInsightsPathId: x.networkInsightsPathId, CreatedDate: x.createdDate, Source: x.source,
  Destination: x.destination || "", SourceIp: x.sourceIp || "", DestinationIp: x.destinationIp || "",
  Protocol: x.protocol, DestinationPort: x.destinationPort ? Number(x.destinationPort) : null, Tags: tagsFromXml(x.tagSet),
});
export const createNetworkInsightsPath = (source, destination, protocol, destinationPort, tags) => call("CreateNetworkInsightsPath", {
  Source: source, Destination: destination || undefined, Protocol: protocol, DestinationPort: destinationPort || undefined,
  TagSpecification: tagSpec("network-insights-path", tags),
}).then((r) => nipFromXml(r.networkInsightsPath));
export async function describeNetworkInsightsPaths() {
  const r = await call("DescribeNetworkInsightsPaths");
  return asList(r.networkInsightsPathSet?.item).map(nipFromXml);
}
export const describeNetworkInsightsPath = (id) => describeNetworkInsightsPaths().then((xs) => xs.find((p) => p.NetworkInsightsPathId === id));
export const deleteNetworkInsightsPath = (id) => call("DeleteNetworkInsightsPath", { NetworkInsightsPathId: id });

const niaFromXml = (x) => ({
  NetworkInsightsAnalysisId: x.networkInsightsAnalysisId, NetworkInsightsPathId: x.networkInsightsPathId,
  StartDate: x.startDate, Status: x.status, NetworkPathFound: x.networkPathFound === "true",
  ForwardPathComponents: asList(x.forwardPathComponentSet?.item).map((c) => ({ SequenceNumber: Number(c.sequenceNumber), Component: { Id: c.component?.id, Name: c.component?.name } })),
  Explanations: asList(x.explanationSet?.item).map((e) => ({ ExplanationCode: e.explanationCode, ComponentId: e.component?.id, Direction: e.direction, State: e.state, Explanation: e.explanation })),
});
export const startNetworkInsightsAnalysis = (pathId) => call("StartNetworkInsightsAnalysis", { NetworkInsightsPathId: pathId }).then((r) => niaFromXml(r.networkInsightsAnalysis));
export async function describeNetworkInsightsAnalyses(pathId) {
  const r = await call("DescribeNetworkInsightsAnalyses", { NetworkInsightsPathId: pathId });
  return asList(r.networkInsightsAnalysisSet?.item).map(niaFromXml);
}
export const deleteNetworkInsightsAnalysis = (id) => call("DeleteNetworkInsightsAnalysis", { NetworkInsightsAnalysisId: id });
