/* VPN / Client VPN / Traffic Mirroring / Transit Gateway extras / VPC CIDRs over the EC2 Query wire. */
import { asList } from "../../../common/wire.js";
import { ec2call as call, tagsFromXml, describeVpcs, describeSubnets, describeTransitGateways, describeTransitGatewayAttachments } from "./api.js";

export { describeVpcs, describeSubnets, describeTransitGateways, describeTransitGatewayAttachments };
const L = (r, path) => asList(path.split(".").reduce((o, k) => o?.[k], r)?.item ?? path.split(".").reduce((o, k) => o?.[k], r));
const tags = (x) => tagsFromXml(x.tagSet);
const items = (x) => asList(x?.item);
const tagSpec = (t, name) => (name ? [{ ResourceType: t, Tag: [{ Key: "Name", Value: name }] }] : undefined);
export const nameOf = (r) => r.Tags?.Name || "-";

// ── customer / virtual private gateways ──
export const describeCustomerGateways = () => call("DescribeCustomerGateways").then((r) => items(r.customerGatewaySet).map((x) => ({ Id: x.customerGatewayId, State: x.state, Type: x.type, Ip: x.ipAddress, Asn: x.bgpAsn, Device: x.deviceName || "", Tags: tags(x) })));
export const createCustomerGateway = (v) => call("CreateCustomerGateway", { IpAddress: v.ip, BgpAsn: v.asn || "65000", Type: "ipsec.1", DeviceName: v.device || undefined, TagSpecification: tagSpec("customer-gateway", v.name) });
export const deleteCustomerGateway = (id) => call("DeleteCustomerGateway", { CustomerGatewayId: id });
export const describeVpnGateways = () => call("DescribeVpnGateways").then((r) => items(r.vpnGatewaySet).map((x) => ({ Id: x.vpnGatewayId, State: x.state, Type: x.type, Asn: x.amazonSideAsn, Vpcs: items(x.attachments).map((a) => a.vpcId), Tags: tags(x) })));
export const createVpnGateway = (v) => call("CreateVpnGateway", { Type: "ipsec.1", AmazonSideAsn: v.asn || undefined, TagSpecification: tagSpec("vpn-gateway", v.name) });
export const deleteVpnGateway = (id) => call("DeleteVpnGateway", { VpnGatewayId: id });
export const attachVpnGateway = (id, vpc) => call("AttachVpnGateway", { VpnGatewayId: id, VpcId: vpc });
export const detachVpnGateway = (id, vpc) => call("DetachVpnGateway", { VpnGatewayId: id, VpcId: vpc });

// ── VPN connections ──
const vpnFrom = (x) => ({
  Id: x.vpnConnectionId, State: x.state, Cgw: x.customerGatewayId, Vgw: x.vpnGatewayId || "", Tgw: x.transitGatewayId || "", StaticOnly: x.options?.staticRoutesOnly === "true",
  Routes: items(x.routes).map((r) => r.destinationCidrBlock),
  Tunnels: items(x.options?.tunnelOptionSet).map((t, i) => ({ N: i + 1, Outside: t.outsideIpAddress, Inside: t.tunnelInsideCidr, Psk: t.preSharedKey, P1: t.phase1LifetimeSeconds, P2: t.phase2LifetimeSeconds, Dpd: t.dpdTimeoutSeconds, DpdAction: t.dpdTimeoutAction, Startup: t.startupAction, Ike: items(t.ikeVersionSet).map((v) => v.value).join(", "),
    Status: items(x.vgwTelemetry)[i]?.status, Message: items(x.vgwTelemetry)[i]?.statusMessage })),
  Tags: tags(x),
});
export const describeVpnConnections = () => call("DescribeVpnConnections").then((r) => items(r.vpnConnectionSet).map(vpnFrom));
export const createVpnConnection = (v) => call("CreateVpnConnection", { CustomerGatewayId: v.cgw, VpnGatewayId: v.target === "vgw" ? v.vgw : undefined, TransitGatewayId: v.target === "tgw" ? v.tgw : undefined, Type: "ipsec.1", Options: { StaticRoutesOnly: v.routing === "bgp" ? "false" : "true" }, TagSpecification: tagSpec("vpn-connection", v.name) });
export const deleteVpnConnection = (id) => call("DeleteVpnConnection", { VpnConnectionId: id });
export const createVpnConnectionRoute = (id, cidr) => call("CreateVpnConnectionRoute", { VpnConnectionId: id, DestinationCidrBlock: cidr });
export const deleteVpnConnectionRoute = (id, cidr) => call("DeleteVpnConnectionRoute", { VpnConnectionId: id, DestinationCidrBlock: cidr });
export const modifyVpnTunnelOptions = (id, ip, o) => call("ModifyVpnTunnelOptions", { VpnConnectionId: id, VpnTunnelOutsideIpAddress: ip, TunnelOptions: o });
export const describeVpnConcentrators = () => call("DescribeVpnConcentrators").then((r) => items(r.vpnConcentratorSet).map((x) => ({ Id: x.vpnConcentratorId, State: x.state, Tgw: x.transitGatewayId, Type: x.type, Tags: tags(x) })));
export const createVpnConcentrator = (v) => call("CreateVpnConcentrator", { TransitGatewayId: v.tgw, Type: "ipsec.1", TagSpecification: tagSpec("vpn-concentrator", v.name) });
export const deleteVpnConcentrator = (id) => call("DeleteVpnConcentrator", { VpnConcentratorId: id });

// ── route propagation / edge associations ──
export const enableVgwRoutePropagation = (gw, rt) => call("EnableVgwRoutePropagation", { GatewayId: gw, RouteTableId: rt });
export const disableVgwRoutePropagation = (gw, rt) => call("DisableVgwRoutePropagation", { GatewayId: gw, RouteTableId: rt });
export const associateEdge = (rt, gw) => call("AssociateRouteTable", { RouteTableId: rt, GatewayId: gw });
export const disassociateRouteTable = (id) => call("DisassociateRouteTable", { AssociationId: id });
export const describeInternetGatewaysLite = () => call("DescribeInternetGateways").then((r) => items(r.internetGatewaySet).map((x) => ({ Id: x.internetGatewayId, Vpcs: items(x.attachmentSet).map((a) => a.vpcId) })));
export const describeRouteTableEdge = (rt) => call("DescribeRouteTables", { RouteTableId: [rt] }).then((r) => {
  const x = items(r.routeTableSet)[0] || {};
  return { edge: items(x.associationSet).filter((a) => a.gatewayId).map((a) => ({ Id: a.routeTableAssociationId, Gateway: a.gatewayId, State: a.associationState?.state })),
    propagating: items(x.propagatingVgwSet).map((g) => g.gatewayId),
    routes: items(x.routeSet).map((o) => ({ Dest: o.destinationCidrBlock, Target: o.gatewayId || o.natGatewayId || o.transitGatewayId || o.vpcPeeringConnectionId || o.networkInterfaceId || o.instanceId, State: o.state, Origin: o.origin })) };
});

// ── VPC CIDRs ──
export const describeVpcCidrs = (vpc) => call("DescribeVpcs", { VpcId: [vpc] }).then((r) => {
  const x = items(r.vpcSet)[0] || {};
  return [...items(x.cidrBlockAssociationSet).map((a) => ({ Id: a.associationId, Cidr: a.cidrBlock, Kind: a.associationId.includes("primary") ? "IPv4 (primary)" : "IPv4", State: a.cidrBlockState?.state })),
    ...items(x.ipv6CidrBlockAssociationSet).map((a) => ({ Id: a.associationId, Cidr: a.ipv6CidrBlock, Kind: "IPv6", State: a.ipv6CidrBlockState?.state }))];
});
export const associateVpcCidr = (vpc, cidr, v6) => call("AssociateVpcCidrBlock", v6 ? { VpcId: vpc, AmazonProvidedIpv6CidrBlock: "true" } : { VpcId: vpc, CidrBlock: cidr });
export const disassociateVpcCidr = (id) => call("DisassociateVpcCidrBlock", { AssociationId: id });

// ── Client VPN ──
export const describeClientVpnEndpoints = () => call("DescribeClientVpnEndpoints").then((r) => items(r.clientVpnEndpoint).map((x) => ({ Id: x.clientVpnEndpointId, State: x.status?.code, Description: x.description || "", ClientCidr: x.clientCidrBlock, Dns: x.dnsName, Vpc: x.vpcId || "-", Split: x.splitTunnel === "true", Transport: x.transportProtocol, Port: x.vpnPort, Auth: items(x.authenticationOptions).map((a) => a.type).join(", "), Tags: tags(x) })));
export const createClientVpnEndpoint = (v) => call("CreateClientVpnEndpoint", {
  ClientCidrBlock: v.cidr, ServerCertificateArn: v.serverCert, TransportProtocol: v.transport || "udp", SplitTunnel: v.split ? "true" : undefined, VpcId: v.vpc || undefined, Description: v.description || undefined,
  Authentication: [v.auth === "directory-service-authentication" ? { Type: v.auth, ActiveDirectory: { DirectoryId: v.authArn } } : v.auth === "federated-authentication" ? { Type: v.auth, FederatedAuthentication: { SAMLProviderArn: v.authArn } } : { Type: "certificate-authentication", MutualAuthentication: { ClientRootCertificateChainArn: v.authArn } }],
  ConnectionLogOptions: { Enabled: "false" }, TagSpecification: tagSpec("client-vpn-endpoint", v.name) });
export const deleteClientVpnEndpoint = (id) => call("DeleteClientVpnEndpoint", { ClientVpnEndpointId: id });
export const describeClientVpnTargets = (id) => call("DescribeClientVpnTargetNetworks", { ClientVpnEndpointId: id }).then((r) => items(r.clientVpnTargetNetworks).map((x) => ({ Id: x.associationId, Subnet: x.targetNetworkId, Vpc: x.vpcId, State: x.status?.code })));
export const associateClientVpnTarget = (id, subnet) => call("AssociateClientVpnTargetNetwork", { ClientVpnEndpointId: id, SubnetId: subnet });
export const disassociateClientVpnTarget = (id, assoc) => call("DisassociateClientVpnTargetNetwork", { ClientVpnEndpointId: id, AssociationId: assoc });
export const describeClientVpnRules = (id) => call("DescribeClientVpnAuthorizationRules", { ClientVpnEndpointId: id }).then((r) => items(r.authorizationRule).map((x) => ({ Id: `${x.destinationCidr}|${x.groupId || "*"}`, Cidr: x.destinationCidr, Group: x.groupId || "", All: x.accessAll === "true", Description: x.description || "", State: x.status?.code })));
export const authorizeClientVpnIngress = (id, cidr, group) => call("AuthorizeClientVpnIngress", { ClientVpnEndpointId: id, TargetNetworkCidr: cidr, AuthorizeAllGroups: group ? undefined : "true", AccessGroupId: group || undefined });
export const revokeClientVpnIngress = (id, r) => call("RevokeClientVpnIngress", { ClientVpnEndpointId: id, TargetNetworkCidr: r.Cidr, RevokeAllGroups: r.All ? "true" : undefined, AccessGroupId: r.Group || undefined });
export const describeClientVpnRoutes = (id) => call("DescribeClientVpnRoutes", { ClientVpnEndpointId: id }).then((r) => items(r.routes).map((x) => ({ Id: `${x.destinationCidr}|${x.targetSubnet}`, Dest: x.destinationCidr, Subnet: x.targetSubnet, Origin: x.origin, State: x.status?.code, Description: x.description || "" })));
export const createClientVpnRoute = (id, dest, subnet) => call("CreateClientVpnRoute", { ClientVpnEndpointId: id, DestinationCidrBlock: dest, TargetVpcSubnetId: subnet });
export const deleteClientVpnRoute = (id, r) => call("DeleteClientVpnRoute", { ClientVpnEndpointId: id, DestinationCidrBlock: r.Dest, TargetVpcSubnetId: r.Subnet });
export const describeClientVpnConnections = (id) => call("DescribeClientVpnConnections", { ClientVpnEndpointId: id }).then((r) => items(r.connections));

// ── Traffic Mirroring ──
export const describeMirrorTargets = () => call("DescribeTrafficMirrorTargets").then((r) => items(r.trafficMirrorTargetSet).map((x) => ({ Id: x.trafficMirrorTargetId, Type: x.type, Eni: x.networkInterfaceId || "", Nlb: x.networkLoadBalancerArn || "", Gwlbe: x.gatewayLoadBalancerEndpointId || "", Description: x.description || "", Tags: tags(x) })));
export const createMirrorTarget = (v) => call("CreateTrafficMirrorTarget", { NetworkInterfaceId: v.eni || undefined, NetworkLoadBalancerArn: v.nlb || undefined, Description: v.description || undefined, TagSpecification: tagSpec("traffic-mirror-target", v.name) });
export const deleteMirrorTarget = (id) => call("DeleteTrafficMirrorTarget", { TrafficMirrorTargetId: id });
const ruleFrom = (x) => ({ Id: x.trafficMirrorFilterRuleId, Direction: x.trafficDirection, Number: x.ruleNumber, Action: x.ruleAction, Protocol: x.protocol || "all", Src: x.sourceCidrBlock, Dst: x.destinationCidrBlock, DPort: x.destinationPortRange ? `${x.destinationPortRange.fromPort}-${x.destinationPortRange.toPort}` : "all" });
export const describeMirrorFilters = () => call("DescribeTrafficMirrorFilters").then((r) => items(r.trafficMirrorFilterSet).map((x) => ({ Id: x.trafficMirrorFilterId, Description: x.description || "", Services: items(x.networkServiceSet).join(", ") || "-", Rules: [...items(x.ingressFilterRuleSet), ...items(x.egressFilterRuleSet)].map(ruleFrom), Tags: tags(x) })));
export const createMirrorFilter = (v) => call("CreateTrafficMirrorFilter", { Description: v.description || undefined, NetworkService: v.dns ? ["amazon-dns"] : undefined, TagSpecification: tagSpec("traffic-mirror-filter", v.name) });
export const deleteMirrorFilter = (id) => call("DeleteTrafficMirrorFilter", { TrafficMirrorFilterId: id });
export const createMirrorRule = (fid, v) => call("CreateTrafficMirrorFilterRule", { TrafficMirrorFilterId: fid, TrafficDirection: v.direction, RuleNumber: v.number, RuleAction: v.action, SourceCidrBlock: v.src || "0.0.0.0/0", DestinationCidrBlock: v.dst || "0.0.0.0/0", Protocol: v.protocol || undefined, DestinationPortRange: v.port ? { FromPort: v.port, ToPort: v.port } : undefined });
export const deleteMirrorRule = (id) => call("DeleteTrafficMirrorFilterRule", { TrafficMirrorFilterRuleId: id });
export const describeMirrorSessions = () => call("DescribeTrafficMirrorSessions").then((r) => items(r.trafficMirrorSessionSet).map((x) => ({ Id: x.trafficMirrorSessionId, Target: x.trafficMirrorTargetId, Filter: x.trafficMirrorFilterId, Eni: x.networkInterfaceId, Number: x.sessionNumber, PacketLength: x.packetLength || "-", Vni: x.virtualNetworkId, Description: x.description || "", Tags: tags(x) })));
export const createMirrorSession = (v) => call("CreateTrafficMirrorSession", { NetworkInterfaceId: v.eni, TrafficMirrorTargetId: v.target, TrafficMirrorFilterId: v.filter, SessionNumber: v.number, PacketLength: v.packet || undefined, Description: v.description || undefined, TagSpecification: tagSpec("traffic-mirror-session", v.name) });
export const deleteMirrorSession = (id) => call("DeleteTrafficMirrorSession", { TrafficMirrorSessionId: id });
export const describeEnis = () => call("DescribeNetworkInterfaces").then((r) => items(r.networkInterfaceSet).map((x) => x.networkInterfaceId));

// ── TGW extras ──
export const describePolicyTables = () => call("DescribeTransitGatewayPolicyTables").then((r) => items(r.transitGatewayPolicyTables).map((x) => ({ Id: x.transitGatewayPolicyTableId, Tgw: x.transitGatewayId, State: x.state, Created: x.creationTime })));
export const createPolicyTable = (v) => call("CreateTransitGatewayPolicyTable", { TransitGatewayId: v.tgw });
export const deletePolicyTable = (id) => call("DeleteTransitGatewayPolicyTable", { TransitGatewayPolicyTableId: id });
export const policyTableAssocs = (id) => call("GetTransitGatewayPolicyTableAssociations", { TransitGatewayPolicyTableId: id }).then((r) => items(r.associations).map((x) => ({ Id: x.transitGatewayAttachmentId, Resource: x.resourceId, State: x.state })));
export const associatePolicyTable = (id, att) => call("AssociateTransitGatewayPolicyTable", { TransitGatewayPolicyTableId: id, TransitGatewayAttachmentId: att });
export const disassociatePolicyTable = (id, att) => call("DisassociateTransitGatewayPolicyTable", { TransitGatewayPolicyTableId: id, TransitGatewayAttachmentId: att });
export const describeMulticastDomains = () => call("DescribeTransitGatewayMulticastDomains").then((r) => items(r.transitGatewayMulticastDomains).map((x) => ({ Id: x.transitGatewayMulticastDomainId, Tgw: x.transitGatewayId, State: x.state, Igmp: x.options?.igmpv2Support, StaticSources: x.options?.staticSourcesSupport, Created: x.creationTime })));
export const createMulticastDomain = (v) => call("CreateTransitGatewayMulticastDomain", { TransitGatewayId: v.tgw, Options: { Igmpv2Support: v.igmp ? "enable" : "disable", StaticSourcesSupport: v.sources ? "enable" : "disable" } });
export const deleteMulticastDomain = (id) => call("DeleteTransitGatewayMulticastDomain", { TransitGatewayMulticastDomainId: id });
export const multicastAssocs = (id) => call("GetTransitGatewayMulticastDomainAssociations", { TransitGatewayMulticastDomainId: id }).then((r) => items(r.multicastDomainAssociations).map((x) => ({ Id: x.subnet?.subnetId, Attachment: x.transitGatewayAttachmentId, Resource: x.resourceId, State: x.subnet?.state })));
export const associateMulticast = (id, att, subnet) => call("AssociateTransitGatewayMulticastDomain", { TransitGatewayMulticastDomainId: id, TransitGatewayAttachmentId: att, SubnetIds: [subnet] });
export const disassociateMulticast = (id, att, subnet) => call("DisassociateTransitGatewayMulticastDomain", { TransitGatewayMulticastDomainId: id, TransitGatewayAttachmentId: att, SubnetIds: [subnet] });
export const multicastGroups = (id) => call("SearchTransitGatewayMulticastGroups", { TransitGatewayMulticastDomainId: id }).then((r) => items(r.multicastGroups).map((x, i) => ({ Id: `${x.groupIpAddress}|${x.networkInterfaceId}|${i}`, Group: x.groupIpAddress, Eni: x.networkInterfaceId, Role: x.groupMember === "true" ? "member" : "source" })));
export const registerMulticast = (id, role, group, eni) => call(role === "source" ? "RegisterTransitGatewayMulticastGroupSources" : "RegisterTransitGatewayMulticastGroupMembers", { TransitGatewayMulticastDomainId: id, GroupIpAddress: group, NetworkInterfaceIds: [eni] });
export const deregisterMulticast = (id, r) => call(r.Role === "source" ? "DeregisterTransitGatewayMulticastGroupSources" : "DeregisterTransitGatewayMulticastGroupMembers", { TransitGatewayMulticastDomainId: id, GroupIpAddress: r.Group, NetworkInterfaceIds: [r.Eni] });
export const describeMeteringPolicies = () => call("DescribeTransitGatewayMeteringPolicies").then((r) => items(r.transitGatewayMeteringPolicySet).map((x) => ({ Id: x.transitGatewayMeteringPolicyId, Tgw: x.transitGatewayId, State: x.state, Middleboxes: items(x.middleboxAttachmentIdSet).join(", ") || "-" })));
export const createMeteringPolicy = (v) => call("CreateTransitGatewayMeteringPolicy", { TransitGatewayId: v.tgw });
export const deleteMeteringPolicy = (id) => call("DeleteTransitGatewayMeteringPolicy", { TransitGatewayMeteringPolicyId: id });
export const meteringEntries = (id) => call("GetTransitGatewayMeteringPolicyEntries", { TransitGatewayMeteringPolicyId: id }).then((r) => items(r.transitGatewayMeteringPolicyEntries).map((x) => ({ Id: x.policyRuleNumber, Number: x.policyRuleNumber, Account: x.meteredAccount, Protocol: x.policyRule?.protocol || "all", Src: x.policyRule?.sourceCidrBlock || "any", Dst: x.policyRule?.destinationCidrBlock || "any" })));
export const createMeteringEntry = (id, v) => call("CreateTransitGatewayMeteringPolicyEntry", { TransitGatewayMeteringPolicyId: id, PolicyRuleNumber: v.number, MeteredAccount: v.account || undefined, PolicyRule: { SourceCidrBlock: v.src || undefined, DestinationCidrBlock: v.dst || undefined, Protocol: v.protocol || undefined } });
export const deleteMeteringEntry = (id, n) => call("DeleteTransitGatewayMeteringPolicyEntry", { TransitGatewayMeteringPolicyId: id, PolicyRuleNumber: n });
