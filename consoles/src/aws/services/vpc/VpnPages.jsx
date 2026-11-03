/* Site-to-Site VPN, Client VPN, Traffic Mirroring and Transit Gateway extras — real lists/forms over the EC2 Query wire. */
import Box from "@cloudscape-design/components/box";
import Table from "@cloudscape-design/components/table";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { ResourceList } from "./Crud.jsx";
import * as x from "./apiExtras.js";

const col = (id, header, cell, extra = {}) => ({ id, header, cell, ...extra });
const name = col("name", "Name", (r) => x.nameOf(r));
const opts = (load, f) => async () => (await load()).map((r) => f(r));
const vpcOpts = opts(x.describeVpcs, (v) => ({ value: v.VpcId, label: v.VpcId }));
const subnetOpts = opts(x.describeSubnets, (s) => ({ value: s.SubnetId, label: `${s.SubnetId} (${s.CidrBlock})` }));
const tgwOpts = opts(x.describeTransitGateways, (g) => ({ value: g.TransitGatewayId, label: g.TransitGatewayId }));
const eniOpts = async () => (await x.describeEnis()).map((v) => ({ value: v, label: v }));
const nameField = { key: "name", label: "Name tag" };
const SubTable = ({ title, items, columns, empty }) => (
  <Table variant="container" header={<Box variant="h3">{title}</Box>} items={items} columnDefinitions={columns} empty={<Box textAlign="center">{empty || "None"}</Box>} />
);

export const CustomerGateways = () => (
  <ResourceList title="Customer gateways" capId="aws.vpc.vpn" trackBy="Id" load={x.describeCustomerGateways}
    columns={[name, col("id", "Customer gateway ID", (r) => r.Id, { isRowHeader: true }), col("state", "State", (r) => r.State), col("type", "Type", (r) => r.Type), col("ip", "IP address", (r) => r.Ip), col("asn", "BGP ASN", (r) => r.Asn), col("dev", "Device", (r) => r.Device || "-")]}
    create={{ label: "Create customer gateway", fields: [nameField, { key: "asn", label: "BGP ASN", default: "65000", required: true }, { key: "ip", label: "IP address", required: true, placeholder: "203.0.113.12" }, { key: "device", label: "Device" }], submit: (v) => x.createCustomerGateway(v) }}
    del={{ label: "Delete customer gateway", type: "customer gateway", run: (r) => x.deleteCustomerGateway(r.Id) }} />
);

export const VirtualPrivateGateways = () => (
  <ResourceList title="Virtual private gateways" capId="aws.vpc.vpn" trackBy="Id" load={x.describeVpnGateways}
    columns={[name, col("id", "Virtual private gateway ID", (r) => r.Id, { isRowHeader: true }), col("state", "State", (r) => (r.Vpcs.length ? "attached" : "detached")), col("vpc", "VPC", (r) => r.Vpcs.join(", ") || "-"), col("type", "Type", (r) => r.Type), col("asn", "Amazon ASN", (r) => r.Asn)]}
    create={{ label: "Create virtual private gateway", fields: [nameField, { key: "asn", label: "Amazon ASN (64512-65534)", description: "Leave empty for the default 64512." }], submit: (v) => x.createVpnGateway(v) }}
    actions={[
      { text: "Attach to VPC", needs: "one", fields: [{ key: "vpc", label: "VPC", type: "select", required: true, options: vpcOpts }], submit: ([g], v) => x.attachVpnGateway(g.Id, v.vpc) },
      { text: "Detach from VPC", needs: "one", submit: async ([g]) => { for (const v of g.Vpcs) await x.detachVpnGateway(g.Id, v); } },
    ]}
    del={{ label: "Delete virtual private gateway", type: "virtual private gateway", run: (r) => x.deleteVpnGateway(r.Id) }} />
);

export const VpnConcentrators = () => (
  <ResourceList title="Site-to-Site VPN Concentrators" capId="aws.vpc.vpn" trackBy="Id" load={x.describeVpnConcentrators}
    columns={[name, col("id", "VPN concentrator ID", (r) => r.Id, { isRowHeader: true }), col("state", "State", (r) => r.State), col("tgw", "Transit gateway", (r) => r.Tgw), col("type", "Type", (r) => r.Type)]}
    create={{ label: "Create VPN concentrator", fields: [nameField, { key: "tgw", label: "Transit gateway", type: "select", required: true, options: tgwOpts }], submit: (v) => x.createVpnConcentrator(v) }}
    del={{ label: "Delete VPN concentrator", type: "VPN concentrator", run: (r) => x.deleteVpnConcentrator(r.Id) }} />
);

const cgwOpts = opts(x.describeCustomerGateways, (c) => ({ value: c.Id, label: `${c.Id} (${c.Ip})` }));
const vgwOpts = opts(x.describeVpnGateways, (g) => ({ value: g.Id, label: g.Id }));

export const VpnConnections = () => (
  <ResourceList title="Site-to-Site VPN connections" capId="aws.vpc.vpn" trackBy="Id" load={x.describeVpnConnections}
    columns={[name, col("id", "VPN ID", (r) => r.Id, { isRowHeader: true }), col("state", "State", (r) => r.State), col("target", "Virtual private gateway / Transit gateway", (r) => r.Vgw || r.Tgw), col("cgw", "Customer gateway", (r) => r.Cgw),
      col("routing", "Routing", (r) => (r.StaticOnly ? "Static" : "Dynamic (BGP)")), col("tun", "Tunnel 1 / 2 status", (r) => r.Tunnels.map((t) => t.Status).join(" / "))]}
    create={{ label: "Create VPN connection", fields: [nameField,
      { key: "target", label: "Target gateway type", type: "select", required: true, default: "vgw", options: [{ value: "vgw", label: "Virtual private gateway" }, { value: "tgw", label: "Transit gateway" }] },
      { key: "vgw", label: "Virtual private gateway", type: "select", options: vgwOpts, description: "Used when the target is a virtual private gateway." },
      { key: "tgw", label: "Transit gateway", type: "select", options: tgwOpts, description: "Used when the target is a transit gateway." },
      { key: "cgw", label: "Customer gateway", type: "select", required: true, options: cgwOpts },
      { key: "routing", label: "Routing options", type: "select", required: true, default: "static", options: [{ value: "static", label: "Static" }, { value: "bgp", label: "Dynamic (requires BGP)" }] }], submit: (v) => x.createVpnConnection(v) }}
    actions={[
      { text: "Add static route", needs: "one", fields: [{ key: "cidr", label: "IP prefix", required: true, placeholder: "192.168.0.0/24" }], submit: ([c], v) => x.createVpnConnectionRoute(c.Id, v.cidr) },
    ]}
    del={{ label: "Delete VPN connection", type: "VPN connection", run: (r) => x.deleteVpnConnection(r.Id) }}
    detail={(c, reload) => [
      { id: "tunnel", label: "Tunnel details", content: <SubTable title="Tunnels" items={c.Tunnels} empty="No tunnels"
        columns={[col("n", "Tunnel number", (t) => t.N), col("ip", "Outside IP address", (t) => t.Outside), col("in", "Inside IPv4 CIDR", (t) => t.Inside), col("st", "Status", (t) => t.Status), col("msg", "Status details", (t) => t.Message), col("psk", "Pre-shared key", (t) => t.Psk),
          col("p1", "Phase 1 lifetime (s)", (t) => t.P1), col("p2", "Phase 2 lifetime (s)", (t) => t.P2), col("dpd", "DPD timeout (s)", (t) => `${t.Dpd} (${t.DpdAction})`), col("ike", "IKE versions", (t) => t.Ike), col("su", "Startup action", (t) => t.Startup)]} /> },
      { id: "routes", label: "Static routes", content: <SubTable title="Static routes" items={c.Routes.map((r) => ({ r }))} empty={c.StaticOnly ? "No static routes" : "Dynamic (BGP) connection: static routes are not applicable"} columns={[col("r", "IP prefixes", (z) => z.r), col("s", "Source", () => "Static"), col("st", "State", () => "available")]} /> },
      { id: "tags", label: "Tags", content: <SubTable title="Tags" items={Object.entries(c.Tags).map(([k, v]) => ({ k, v }))} columns={[col("k", "Key", (z) => z.k), col("v", "Value", (z) => z.v)]} /> },
    ]} />
);

const mirrorTargetOpts = opts(x.describeMirrorTargets, (t) => ({ value: t.Id, label: `${t.Id} (${t.Eni || t.Nlb || t.Gwlbe})` }));
const mirrorFilterOpts = opts(x.describeMirrorFilters, (f) => ({ value: f.Id, label: f.Id }));

export const MirrorTargets = () => (
  <ResourceList title="Mirror targets" capId="aws.vpc.traffic-mirroring" trackBy="Id" load={x.describeMirrorTargets}
    columns={[name, col("id", "Target ID", (r) => r.Id, { isRowHeader: true }), col("type", "Target type", (r) => r.Type), col("res", "Target", (r) => r.Eni || r.Nlb || r.Gwlbe), col("d", "Description", (r) => r.Description || "-")]}
    create={{ label: "Create traffic mirror target", fields: [nameField, { key: "eni", label: "Target network interface", type: "select", options: eniOpts }, { key: "nlb", label: "Network Load Balancer ARN" }, { key: "description", label: "Description" }], submit: (v) => x.createMirrorTarget(v) }}
    del={{ label: "Delete", type: "mirror target", run: (r) => x.deleteMirrorTarget(r.Id) }} />
);

export const MirrorFilters = () => (
  <ResourceList title="Mirror filters" capId="aws.vpc.traffic-mirroring" trackBy="Id" load={x.describeMirrorFilters}
    columns={[name, col("id", "Filter ID", (r) => r.Id, { isRowHeader: true }), col("d", "Description", (r) => r.Description || "-"), col("svc", "Network services", (r) => r.Services), col("n", "Rules", (r) => r.Rules.length)]}
    create={{ label: "Create traffic mirror filter", fields: [nameField, { key: "description", label: "Description" }, { key: "dns", label: "Mirror Amazon DNS traffic", type: "checkbox" }], submit: (v) => x.createMirrorFilter(v) }}
    actions={[{ text: "Add rule", needs: "one", fields: [
      { key: "direction", label: "Traffic direction", type: "select", required: true, default: "ingress", options: ["ingress", "egress"] },
      { key: "number", label: "Rule number (1-32766)", required: true }, { key: "action", label: "Rule action", type: "select", required: true, default: "accept", options: ["accept", "reject"] },
      { key: "protocol", label: "Protocol number (6=TCP, 17=UDP)" }, { key: "src", label: "Source CIDR", default: "0.0.0.0/0" }, { key: "dst", label: "Destination CIDR", default: "0.0.0.0/0" }, { key: "port", label: "Destination port (TCP/UDP)" }], submit: ([f], v) => x.createMirrorRule(f.Id, v) }]}
    del={{ label: "Delete", type: "mirror filter", run: (r) => x.deleteMirrorFilter(r.Id) }}
    detail={(f) => [{ id: "rules", label: "Filter rules", content: (
      <ResourceList h2 variant="borderless" title="Filter rules" trackBy="Id" load={async () => f.Rules}
        columns={[col("dir", "Direction", (r) => r.Direction), col("num", "Rule number", (r) => r.Number), col("act", "Action", (r) => r.Action), col("p", "Protocol", (r) => r.Protocol), col("s", "Source CIDR", (r) => r.Src), col("d", "Destination CIDR", (r) => r.Dst), col("dp", "Destination ports", (r) => r.DPort)]}
        del={{ label: "Delete rule", type: "rule", run: (r) => x.deleteMirrorRule(r.Id) }} />) }]} />
);

export const MirrorSessions = () => (
  <ResourceList title="Mirror sessions" capId="aws.vpc.traffic-mirroring" trackBy="Id" load={x.describeMirrorSessions}
    columns={[name, col("id", "Session ID", (r) => r.Id, { isRowHeader: true }), col("eni", "Source network interface", (r) => r.Eni), col("tgt", "Target", (r) => r.Target), col("f", "Filter", (r) => r.Filter), col("n", "Session number", (r) => r.Number), col("pl", "Packet length", (r) => r.PacketLength), col("vni", "VNI", (r) => r.Vni)]}
    create={{ label: "Create traffic mirror session", fields: [nameField, { key: "eni", label: "Mirror source (network interface)", type: "select", required: true, options: eniOpts }, { key: "target", label: "Mirror target", type: "select", required: true, options: mirrorTargetOpts },
      { key: "filter", label: "Mirror filter", type: "select", required: true, options: mirrorFilterOpts }, { key: "number", label: "Session number (1-32766)", required: true, default: "1" }, { key: "packet", label: "Packet length" }, { key: "description", label: "Description" }], submit: (v) => x.createMirrorSession(v) }}
    del={{ label: "Delete", type: "mirror session", run: (r) => x.deleteMirrorSession(r.Id) }} />
);

export const TransitGatewayPolicyTables = () => (
  <ResourceList title="Transit gateway policy tables" capId="aws.vpc.transit-gateway-advanced" trackBy="Id" load={x.describePolicyTables}
    columns={[col("id", "Policy table ID", (r) => r.Id, { isRowHeader: true }), col("tgw", "Transit gateway", (r) => r.Tgw), col("st", "State", (r) => r.State), col("c", "Creation time", (r) => r.Created)]}
    create={{ label: "Create policy table", fields: [{ key: "tgw", label: "Transit gateway", type: "select", required: true, options: tgwOpts }], submit: (v) => x.createPolicyTable(v) }}
    actions={[{ text: "Associate attachment", needs: "one", fields: [{ key: "att", label: "Attachment", type: "select", required: true, options: opts(x.describeTransitGatewayAttachments, (a) => ({ value: a.AttachmentId, label: `${a.AttachmentId} (${a.ResourceId})` })) }], submit: ([t], v) => x.associatePolicyTable(t.Id, v.att) }]}
    del={{ label: "Delete", type: "policy table", run: (r) => x.deletePolicyTable(r.Id) }}
    detail={(t) => [{ id: "assoc", label: "Associations", content: (
      <ResourceList h2 variant="borderless" title="Associations" trackBy="Id" load={() => x.policyTableAssocs(t.Id)}
        columns={[col("a", "Attachment ID", (r) => r.Id), col("r", "Resource ID", (r) => r.Resource), col("s", "State", (r) => r.State)]}
        del={{ label: "Disassociate", type: "association", run: (r) => x.disassociatePolicyTable(t.Id, r.Id) }} />) }]} />
);

export const TransitGatewayMulticast = () => (
  <ResourceList title="Transit gateway multicast" capId="aws.vpc.transit-gateway-advanced" trackBy="Id" load={x.describeMulticastDomains}
    columns={[col("id", "Multicast domain ID", (r) => r.Id, { isRowHeader: true }), col("tgw", "Transit gateway", (r) => r.Tgw), col("st", "State", (r) => r.State), col("i", "IGMPv2 support", (r) => r.Igmp), col("s", "Static sources support", (r) => r.StaticSources)]}
    create={{ label: "Create multicast domain", fields: [{ key: "tgw", label: "Transit gateway (needs multicast support)", type: "select", required: true, options: tgwOpts }, { key: "igmp", label: "IGMPv2 support", type: "checkbox" }, { key: "sources", label: "Static sources support", type: "checkbox" }], submit: (v) => x.createMulticastDomain(v) }}
    actions={[
      { text: "Associate subnet", needs: "one", fields: [{ key: "att", label: "Attachment", type: "select", required: true, options: opts(x.describeTransitGatewayAttachments, (a) => ({ value: a.AttachmentId, label: `${a.AttachmentId} (${a.ResourceId})` })) }, { key: "subnet", label: "Subnet", type: "select", required: true, options: subnetOpts }], submit: ([d], v) => x.associateMulticast(d.Id, v.att, v.subnet) },
      { text: "Register group member", needs: "one", fields: [{ key: "group", label: "Group IP address", required: true, placeholder: "224.0.0.50" }, { key: "eni", label: "Network interface", type: "select", required: true, options: eniOpts }], submit: ([d], v) => x.registerMulticast(d.Id, "member", v.group, v.eni) },
    ]}
    del={{ label: "Delete", type: "multicast domain", run: (r) => x.deleteMulticastDomain(r.Id) }}
    detail={(d) => [
      { id: "assoc", label: "Associations", content: <ResourceList h2 variant="borderless" title="Subnet associations" trackBy="Id" load={() => x.multicastAssocs(d.Id)}
        columns={[col("s", "Subnet ID", (r) => r.Id), col("a", "Attachment ID", (r) => r.Attachment), col("r", "Resource ID", (r) => r.Resource), col("st", "State", (r) => r.State)]}
        del={{ label: "Disassociate", type: "association", run: (r) => x.disassociateMulticast(d.Id, r.Attachment, r.Id) }} /> },
      { id: "groups", label: "Groups", content: <ResourceList h2 variant="borderless" title="Groups" trackBy="Id" load={() => x.multicastGroups(d.Id)}
        columns={[col("g", "Group IP address", (r) => r.Group), col("e", "Network interface", (r) => r.Eni), col("r", "Type", (r) => r.Role)]}
        del={{ label: "Deregister", type: "group member", run: (r) => x.deregisterMulticast(d.Id, r) }} /> },
    ]} />
);

export const MeteringPolicies = () => (
  <ResourceList title="Metering policies" capId="aws.vpc.transit-gateway-advanced" trackBy="Id" load={x.describeMeteringPolicies}
    columns={[col("id", "Metering policy ID", (r) => r.Id, { isRowHeader: true }), col("tgw", "Transit gateway", (r) => r.Tgw), col("st", "State", (r) => r.State), col("m", "Middlebox attachments", (r) => r.Middleboxes)]}
    create={{ label: "Create metering policy", fields: [{ key: "tgw", label: "Transit gateway", type: "select", required: true, options: tgwOpts }], submit: (v) => x.createMeteringPolicy(v) }}
    actions={[{ text: "Add entry", needs: "one", fields: [{ key: "number", label: "Rule number (1-32766)", required: true }, { key: "src", label: "Source CIDR" }, { key: "dst", label: "Destination CIDR" }, { key: "protocol", label: "Protocol" }, { key: "account", label: "Metered account", type: "select", default: "source-attachment-owner", options: ["source-attachment-owner", "destination-attachment-owner"] }], submit: ([p], v) => x.createMeteringEntry(p.Id, v) }]}
    del={{ label: "Delete", type: "metering policy", run: (r) => x.deleteMeteringPolicy(r.Id) }}
    detail={(p) => [{ id: "entries", label: "Policy entries", content: <ResourceList h2 variant="borderless" title="Policy entries" trackBy="Id" load={() => x.meteringEntries(p.Id)}
      columns={[col("n", "Rule number", (r) => r.Number), col("a", "Metered account", (r) => r.Account), col("p", "Protocol", (r) => r.Protocol), col("s", "Source", (r) => r.Src), col("d", "Destination", (r) => r.Dst)]}
      del={{ label: "Delete entry", type: "entry", run: (r) => x.deleteMeteringEntry(p.Id, r.Number) }} /> }]} />
);

export const ClientVpnEndpoints = () => (
  <ResourceList title="Client VPN endpoints" capId="aws.vpc.vpn" trackBy="Id" load={x.describeClientVpnEndpoints}
    columns={[name, col("id", "Client VPN endpoint ID", (r) => r.Id, { isRowHeader: true }), col("st", "State", (r) => r.State), col("cidr", "Client IPv4 CIDR", (r) => r.ClientCidr), col("vpc", "VPC", (r) => r.Vpc), col("auth", "Authentication", (r) => r.Auth), col("tr", "Transport", (r) => `${r.Transport}/${r.Port}`), col("dns", "DNS name", (r) => r.Dns)]}
    create={{ label: "Create client VPN endpoint", fields: [nameField, { key: "description", label: "Description" }, { key: "cidr", label: "Client IPv4 CIDR (/12-/22)", required: true, placeholder: "10.200.0.0/16" },
      { key: "serverCert", label: "Server certificate ARN", required: true, placeholder: "arn:aws:acm:us-east-1:123456789012:certificate/..." },
      { key: "auth", label: "Authentication", type: "select", required: true, default: "certificate-authentication", options: ["certificate-authentication", "directory-service-authentication", "federated-authentication"] },
      { key: "authArn", label: "Client root certificate ARN / directory ID / SAML provider ARN", required: true },
      { key: "vpc", label: "VPC", type: "select", options: vpcOpts }, { key: "split", label: "Enable split-tunnel", type: "checkbox" }], submit: (v) => x.createClientVpnEndpoint(v) }}
    actions={[{ text: "Associate target network", needs: "one", fields: [{ key: "subnet", label: "Subnet", type: "select", required: true, options: subnetOpts }], submit: ([e], v) => x.associateClientVpnTarget(e.Id, v.subnet) },
      { text: "Authorize ingress", needs: "one", fields: [{ key: "cidr", label: "Destination network (CIDR)", required: true }, { key: "group", label: "Access group ID", description: "Leave empty to allow all users." }], submit: ([e], v) => x.authorizeClientVpnIngress(e.Id, v.cidr, v.group) },
      { text: "Add route", needs: "one", fields: [{ key: "dest", label: "Route destination (CIDR)", required: true }, { key: "subnet", label: "Target VPC subnet", type: "select", required: true, options: subnetOpts }], submit: ([e], v) => x.createClientVpnRoute(e.Id, v.dest, v.subnet) }]}
    del={{ label: "Delete client VPN endpoint", type: "client VPN endpoint", run: (r) => x.deleteClientVpnEndpoint(r.Id) }}
    detail={(e) => [
      { id: "targets", label: "Target network associations", content: <ResourceList h2 variant="borderless" title="Target network associations" trackBy="Id" load={() => x.describeClientVpnTargets(e.Id)}
        columns={[col("a", "Association ID", (r) => r.Id), col("s", "Subnet ID", (r) => r.Subnet), col("v", "VPC", (r) => r.Vpc), col("st", "State", (r) => r.State)]} del={{ label: "Disassociate", type: "association", run: (r) => x.disassociateClientVpnTarget(e.Id, r.Id) }} /> },
      { id: "auth", label: "Authorization rules", content: <ResourceList h2 variant="borderless" title="Authorization rules" trackBy="Id" load={() => x.describeClientVpnRules(e.Id)}
        columns={[col("c", "Destination CIDR", (r) => r.Cidr), col("g", "Group ID", (r) => r.Group || "-"), col("all", "Access", (r) => (r.All ? "All users" : "Group")), col("st", "Status", (r) => r.State)]} del={{ label: "Revoke", type: "authorization rule", run: (r) => x.revokeClientVpnIngress(e.Id, r) }} /> },
      { id: "routes", label: "Route table", content: <ResourceList h2 variant="borderless" title="Route table" trackBy="Id" load={() => x.describeClientVpnRoutes(e.Id)}
        columns={[col("d", "Destination CIDR", (r) => r.Dest), col("s", "Target subnet", (r) => r.Subnet), col("o", "Origin", (r) => r.Origin), col("st", "Status", (r) => r.State)]} del={{ label: "Delete route", type: "route", run: (r) => x.deleteClientVpnRoute(e.Id, r) }} /> },
      { id: "conn", label: "Connections", content: <ResourceList h2 variant="borderless" title="Connections" trackBy="connectionId" load={() => x.describeClientVpnConnections(e.Id)} empty="No active connections (the simulator has no OpenVPN server)"
        columns={[col("i", "Connection ID", (r) => r.connectionId)]} /> },
    ]} />
);

// ── route-table detail tabs ──
export const EdgeAssociationsTab = ({ rt, onChange }) => (
  <ResourceList h2 variant="borderless" title="Edge associations" capId="aws.vpc.edge-associations" trackBy="Id" load={async () => (await x.describeRouteTableEdge(rt.RouteTableId)).edge} empty="No edge associations"
    columns={[col("id", "Association ID", (r) => r.Id), col("gw", "Gateway", (r) => r.Gateway), col("st", "State", (r) => r.State)]}
    create={{ label: "Edit edge associations", fields: [{ key: "gw", label: "Associated gateway", type: "select", required: true, description: "An internet gateway or virtual private gateway attached to this VPC.", options: async () => {
      const igws = (await x.describeInternetGatewaysLite()).filter((g) => g.Vpcs.includes(rt.VpcId)).map((g) => g.Id);
      const vgws = (await x.describeVpnGateways()).filter((g) => g.Vpcs.includes(rt.VpcId)).map((g) => g.Id);
      return [...igws, ...vgws].map((v) => ({ value: v, label: v })); } }], submit: async (v) => { await x.associateEdge(rt.RouteTableId, v.gw); onChange?.(); } }}
    del={{ label: "Disassociate", type: "edge association", run: async (r) => { await x.disassociateRouteTable(r.Id); onChange?.(); } }} />
);

export const RoutePropagationTab = ({ rt, onChange }) => (
  <ResourceList h2 variant="borderless" title="Route propagation" capId="aws.vpc.route-propagation" trackBy="Id" load={async () => (await x.describeRouteTableEdge(rt.RouteTableId)).propagating.map((g) => ({ Id: g }))} empty="Route propagation is not enabled"
    columns={[col("gw", "Virtual private gateway", (r) => r.Id), col("st", "Propagation", () => "Enabled")]}
    create={{ label: "Edit route propagation", fields: [{ key: "gw", label: "Virtual private gateway", type: "select", required: true, options: async () => (await x.describeVpnGateways()).filter((g) => g.Vpcs.includes(rt.VpcId)).map((g) => ({ value: g.Id, label: g.Id })) }],
      submit: async (v) => { await x.enableVgwRoutePropagation(v.gw, rt.RouteTableId); onChange?.(); } }}
    del={{ label: "Disable propagation", type: "route propagation", run: async (r) => { await x.disableVgwRoutePropagation(r.Id, rt.RouteTableId); onChange?.(); } }} />
);

export const VpcCidrsTab = ({ vpcId, onChange }) => (
  <ResourceList h2 variant="borderless" title="CIDRs" capId="aws.vpc.vpcs" trackBy="Id" load={() => x.describeVpcCidrs(vpcId)}
    columns={[col("c", "CIDR", (r) => r.Cidr), col("k", "Type", (r) => r.Kind), col("id", "Association ID", (r) => r.Id), col("s", "Status", (r) => r.State)]}
    create={{ label: "Add new CIDR", fields: [{ key: "cidr", label: "IPv4 CIDR (/16-/28)", placeholder: "10.1.0.0/16" }, { key: "v6", label: "Amazon-provided IPv6 CIDR block", type: "checkbox" }],
      submit: async (v) => { await x.associateVpcCidr(vpcId, v.cidr, v.v6); onChange?.(); } }}
    del={{ label: "Remove CIDR", type: "CIDR", run: async (r) => { await x.disassociateVpcCidr(r.Id); onChange?.(); } }} />
);
