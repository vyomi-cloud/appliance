import Dashboard from "./Dashboard.jsx";
import { Vpcs, VpcDetail, CreateVpc, EditVpcSettings } from "./Vpcs.jsx";
import { Subnets, SubnetDetail, CreateSubnet } from "./Subnets.jsx";
import { RouteTables, RouteTableDetail, EditRoutes, CreateRouteTable } from "./RouteTables.jsx";
import { InternetGateways, InternetGatewayDetail, CreateInternetGateway, AttachInternetGateway } from "./InternetGateways.jsx";
import { NatGateways, NatGatewayDetail, CreateNatGateway } from "./NatGateways.jsx";
import { NetworkAcls } from "./NetworkAcls.jsx";
import { SecurityGroups, SecurityGroupDetail, CreateSecurityGroup, EditInboundRules, EditOutboundRules } from "./SecurityGroups.jsx";
import { ElasticIps, AllocateElasticIp } from "./ElasticIps.jsx";
import { EgressOnlyInternetGateways, DhcpOptionSets, ManagedPrefixLists, PeeringConnections, RouteServers } from "./MiscResources.jsx";
import Settings from "./Settings.jsx";
import * as Honest from "./HonestPages.jsx";

const crumb = (text, ...path) => ({ text, href: `#/vpc/${path.join("/")}` });
const base = [crumb("VPC", "")];

export default {
  nav: [
    { type: "link", text: "VPC dashboard", href: "#/vpc/dashboard" },
    { type: "link", text: "AWS Global View", href: "#/vpc/dashboard" },
    { type: "section", text: "Virtual private cloud", items: [
      { type: "link", text: "Your VPCs", href: "#/vpc/vpcs" },
      { type: "link", text: "Subnets", href: "#/vpc/subnets" },
      { type: "link", text: "Route tables", href: "#/vpc/route-tables" },
      { type: "link", text: "Internet gateways", href: "#/vpc/internet-gateways" },
      { type: "link", text: "Egress-only internet gateways", href: "#/vpc/egress-only-internet-gateways" },
      { type: "link", text: "DHCP option sets", href: "#/vpc/dhcp-option-sets" },
      { type: "link", text: "Elastic IPs", href: "#/vpc/elastic-ips" },
      { type: "link", text: "Managed prefix lists", href: "#/vpc/managed-prefix-lists" },
      { type: "link", text: "NAT gateways", href: "#/vpc/nat-gateways" },
      { type: "link", text: "Peering connections", href: "#/vpc/peering-connections" },
      { type: "link", text: "Route servers", href: "#/vpc/route-servers" },
    ] },
    { type: "section", text: "Security", items: [
      { type: "link", text: "Network ACLs", href: "#/vpc/network-acls" },
      { type: "link", text: "Security groups", href: "#/vpc/security-groups" },
    ] },
    { type: "section", text: "PrivateLink and Lattice", items: [
      { type: "link", text: "Getting started", href: "#/vpc/privatelink-getting-started" },
      { type: "link", text: "Endpoints", href: "#/vpc/endpoints" },
      { type: "link", text: "Endpoint services", href: "#/vpc/endpoint-services" },
      { type: "link", text: "Service networks", href: "#/vpc/service-networks" },
      { type: "link", text: "Lattice services", href: "#/vpc/lattice-services" },
      { type: "link", text: "Resource configurations", href: "#/vpc/resource-configurations" },
      { type: "link", text: "Resource gateways", href: "#/vpc/resource-gateways" },
      { type: "link", text: "Target groups", href: "#/vpc/lattice-target-groups" },
      { type: "link", text: "Domain verifications", href: "#/vpc/domain-verifications" },
    ] },
    { type: "section", text: "DNS firewall", items: [
      { type: "link", text: "Rule groups", href: "#/vpc/dns-firewall-rule-groups" },
      { type: "link", text: "Domain lists", href: "#/vpc/dns-firewall-domain-lists" },
    ] },
    { type: "section", text: "Network Firewall", items: [
      { type: "link", text: "Firewalls", href: "#/vpc/firewalls" },
      { type: "link", text: "Firewall policies", href: "#/vpc/firewall-policies" },
      { type: "link", text: "Network Firewall rule groups", href: "#/vpc/network-firewall-rule-groups" },
      { type: "link", text: "TLS inspection configurations", href: "#/vpc/tls-inspection-configurations" },
      { type: "link", text: "Network Firewall resource groups", href: "#/vpc/network-firewall-resource-groups" },
      { type: "link", text: "VPC endpoint associations", href: "#/vpc/vpc-endpoint-associations" },
      { type: "link", text: "Container associations", href: "#/vpc/container-associations" },
    ] },
    { type: "section", text: "Virtual private network (VPN)", items: [
      { type: "link", text: "Customer gateways", href: "#/vpc/customer-gateways" },
      { type: "link", text: "Virtual private gateways", href: "#/vpc/virtual-private-gateways" },
      { type: "link", text: "Site-to-Site VPN Concentrators", href: "#/vpc/vpn-concentrators" },
      { type: "link", text: "Site-to-Site VPN connections", href: "#/vpc/vpn-connections" },
      { type: "link", text: "Client VPN endpoints", href: "#/vpc/client-vpn-endpoints" },
    ] },
    { type: "section", text: "AWS Verified Access", items: [
      { type: "link", text: "Verified Access instances", href: "#/vpc/verified-access-instances" },
      { type: "link", text: "Verified Access trust providers", href: "#/vpc/verified-access-trust-providers" },
      { type: "link", text: "Verified Access groups", href: "#/vpc/verified-access-groups" },
      { type: "link", text: "Verified Access endpoints", href: "#/vpc/verified-access-endpoints" },
    ] },
    { type: "section", text: "Transit gateways", items: [
      { type: "link", text: "Transit gateways", href: "#/vpc/transit-gateways" },
      { type: "link", text: "Transit gateway attachments", href: "#/vpc/transit-gateway-attachments" },
      { type: "link", text: "Transit gateway policy tables", href: "#/vpc/transit-gateway-policy-tables" },
      { type: "link", text: "Transit gateway route tables", href: "#/vpc/transit-gateway-route-tables" },
      { type: "link", text: "Transit gateway multicast", href: "#/vpc/transit-gateway-multicast" },
      { type: "link", text: "Metering policies", href: "#/vpc/metering-policies" },
    ] },
    { type: "section", text: "Traffic Mirroring", items: [
      { type: "link", text: "Mirror sessions", href: "#/vpc/mirror-sessions" },
      { type: "link", text: "Mirror targets", href: "#/vpc/mirror-targets" },
      { type: "link", text: "Mirror filters", href: "#/vpc/mirror-filters" },
    ] },
    { type: "link", text: "Settings", href: "#/vpc/settings" },
  ],
  routes: [
    { pattern: "/vpc", component: Dashboard, crumbs: () => base },
    { pattern: "/vpc/home", component: Dashboard, crumbs: () => base },
    { pattern: "/vpc/dashboard", component: Dashboard, crumbs: () => [crumb("VPC", ""), crumb("VPC dashboard", "dashboard")] },

    { pattern: "/vpc/vpcs", component: Vpcs, crumbs: () => [crumb("VPC", ""), crumb("Your VPCs", "vpcs")] },
    { pattern: "/vpc/vpcs/:id", component: VpcDetail, crumbs: (p) => [crumb("VPC", ""), crumb("Your VPCs", "vpcs"), crumb(p.id, "vpcs", p.id)] },
    { pattern: "/vpc/vpcs/:id/edit-settings", component: EditVpcSettings, crumbs: (p) => [crumb("VPC", ""), crumb("Your VPCs", "vpcs"), crumb(p.id, "vpcs", p.id), crumb("Edit VPC settings", "vpcs", p.id, "edit-settings")] },
    { pattern: "/vpc/create-vpc", component: CreateVpc, crumbs: () => [crumb("VPC", ""), crumb("Your VPCs", "vpcs"), crumb("Create VPC", "create-vpc")] },

    { pattern: "/vpc/subnets", component: Subnets, crumbs: () => [crumb("VPC", ""), crumb("Subnets", "subnets")] },
    { pattern: "/vpc/subnets/:id", component: SubnetDetail, crumbs: (p) => [crumb("VPC", ""), crumb("Subnets", "subnets"), crumb(p.id, "subnets", p.id)] },
    { pattern: "/vpc/create-subnet", component: CreateSubnet, crumbs: () => [crumb("VPC", ""), crumb("Subnets", "subnets"), crumb("Create subnet", "create-subnet")] },

    { pattern: "/vpc/route-tables", component: RouteTables, crumbs: () => [crumb("VPC", ""), crumb("Route tables", "route-tables")] },
    { pattern: "/vpc/route-tables/:id", component: RouteTableDetail, crumbs: (p) => [crumb("VPC", ""), crumb("Route tables", "route-tables"), crumb(p.id, "route-tables", p.id)] },
    { pattern: "/vpc/route-tables/:id/edit-routes", component: EditRoutes, crumbs: (p) => [crumb("VPC", ""), crumb("Route tables", "route-tables"), crumb(p.id, "route-tables", p.id), crumb("Edit routes", "route-tables", p.id, "edit-routes")] },
    { pattern: "/vpc/create-route-table", component: CreateRouteTable, crumbs: () => [crumb("VPC", ""), crumb("Route tables", "route-tables"), crumb("Create route table", "create-route-table")] },

    { pattern: "/vpc/internet-gateways", component: InternetGateways, crumbs: () => [crumb("VPC", ""), crumb("Internet gateways", "internet-gateways")] },
    { pattern: "/vpc/internet-gateways/:id", component: InternetGatewayDetail, crumbs: (p) => [crumb("VPC", ""), crumb("Internet gateways", "internet-gateways"), crumb(p.id, "internet-gateways", p.id)] },
    { pattern: "/vpc/internet-gateways/:id/attach", component: AttachInternetGateway, crumbs: (p) => [crumb("VPC", ""), crumb("Internet gateways", "internet-gateways"), crumb(p.id, "internet-gateways", p.id), crumb("Attach to VPC", "internet-gateways", p.id, "attach")] },
    { pattern: "/vpc/create-internet-gateway", component: CreateInternetGateway, crumbs: () => [crumb("VPC", ""), crumb("Internet gateways", "internet-gateways"), crumb("Create internet gateway", "create-internet-gateway")] },

    { pattern: "/vpc/nat-gateways", component: NatGateways, crumbs: () => [crumb("VPC", ""), crumb("NAT gateways", "nat-gateways")] },
    { pattern: "/vpc/nat-gateways/:id", component: NatGatewayDetail, crumbs: (p) => [crumb("VPC", ""), crumb("NAT gateways", "nat-gateways"), crumb(p.id, "nat-gateways", p.id)] },
    { pattern: "/vpc/create-nat-gateway", component: CreateNatGateway, crumbs: () => [crumb("VPC", ""), crumb("NAT gateways", "nat-gateways"), crumb("Create NAT gateway", "create-nat-gateway")] },

    { pattern: "/vpc/network-acls", component: NetworkAcls, crumbs: () => [crumb("VPC", ""), crumb("Network ACLs", "network-acls")] },

    { pattern: "/vpc/security-groups", component: SecurityGroups, crumbs: () => [crumb("VPC", ""), crumb("Security Groups", "security-groups")] },
    { pattern: "/vpc/security-groups/:id", component: SecurityGroupDetail, crumbs: (p) => [crumb("VPC", ""), crumb("Security Groups", "security-groups"), crumb(p.id, "security-groups", p.id)] },
    { pattern: "/vpc/security-groups/:id/edit-inbound-rules", component: EditInboundRules, crumbs: (p) => [crumb("VPC", ""), crumb("Security Groups", "security-groups"), crumb(p.id, "security-groups", p.id), crumb("Edit inbound rules", "security-groups", p.id, "edit-inbound-rules")] },
    { pattern: "/vpc/security-groups/:id/edit-outbound-rules", component: EditOutboundRules, crumbs: (p) => [crumb("VPC", ""), crumb("Security Groups", "security-groups"), crumb(p.id, "security-groups", p.id), crumb("Edit outbound rules", "security-groups", p.id, "edit-outbound-rules")] },
    { pattern: "/vpc/create-security-group", component: CreateSecurityGroup, crumbs: () => [crumb("VPC", ""), crumb("Security Groups", "security-groups"), crumb("Create security group", "create-security-group")] },

    { pattern: "/vpc/elastic-ips", component: ElasticIps, crumbs: () => [crumb("VPC", ""), crumb("Elastic IP addresses", "elastic-ips")] },
    { pattern: "/vpc/allocate-elastic-ip", component: AllocateElasticIp, crumbs: () => [crumb("VPC", ""), crumb("Elastic IP addresses", "elastic-ips"), crumb("Allocate Elastic IP address", "allocate-elastic-ip")] },

    { pattern: "/vpc/egress-only-internet-gateways", component: EgressOnlyInternetGateways, crumbs: () => [crumb("VPC", ""), crumb("Egress-only internet gateways", "egress-only-internet-gateways")] },
    { pattern: "/vpc/dhcp-option-sets", component: DhcpOptionSets, crumbs: () => [crumb("VPC", ""), crumb("DHCP option sets", "dhcp-option-sets")] },
    { pattern: "/vpc/managed-prefix-lists", component: ManagedPrefixLists, crumbs: () => [crumb("VPC", ""), crumb("Managed prefix lists", "managed-prefix-lists")] },
    { pattern: "/vpc/peering-connections", component: PeeringConnections, crumbs: () => [crumb("VPC", ""), crumb("Peering connections", "peering-connections")] },
    { pattern: "/vpc/route-servers", component: RouteServers, crumbs: () => [crumb("VPC", ""), crumb("Route servers", "route-servers")] },

    { pattern: "/vpc/privatelink-getting-started", component: Honest.PrivatelinkGettingStarted, crumbs: () => [crumb("VPC", ""), crumb("Getting started", "privatelink-getting-started")] },
    { pattern: "/vpc/endpoints", component: Honest.Endpoints, crumbs: () => [crumb("VPC", ""), crumb("Endpoints", "endpoints")] },
    { pattern: "/vpc/endpoint-services", component: Honest.EndpointServices, crumbs: () => [crumb("VPC", ""), crumb("Endpoint services", "endpoint-services")] },
    { pattern: "/vpc/service-networks", component: Honest.ServiceNetworks, crumbs: () => [crumb("VPC", ""), crumb("Service networks", "service-networks")] },
    { pattern: "/vpc/lattice-services", component: Honest.LatticeServices, crumbs: () => [crumb("VPC", ""), crumb("Lattice services", "lattice-services")] },
    { pattern: "/vpc/resource-configurations", component: Honest.ResourceConfigurations, crumbs: () => [crumb("VPC", ""), crumb("Resource configurations", "resource-configurations")] },
    { pattern: "/vpc/resource-gateways", component: Honest.ResourceGateways, crumbs: () => [crumb("VPC", ""), crumb("Resource gateways", "resource-gateways")] },
    { pattern: "/vpc/lattice-target-groups", component: Honest.LatticeTargetGroups, crumbs: () => [crumb("VPC", ""), crumb("Target groups", "lattice-target-groups")] },
    { pattern: "/vpc/domain-verifications", component: Honest.DomainVerifications, crumbs: () => [crumb("VPC", ""), crumb("Domain verifications", "domain-verifications")] },

    { pattern: "/vpc/dns-firewall-rule-groups", component: Honest.DnsFirewallRuleGroups, crumbs: () => [crumb("VPC", ""), crumb("Rule groups", "dns-firewall-rule-groups")] },
    { pattern: "/vpc/dns-firewall-domain-lists", component: Honest.DnsFirewallDomainLists, crumbs: () => [crumb("VPC", ""), crumb("Domain lists", "dns-firewall-domain-lists")] },

    { pattern: "/vpc/firewalls", component: Honest.Firewalls, crumbs: () => [crumb("VPC", ""), crumb("Firewalls", "firewalls")] },
    { pattern: "/vpc/firewall-policies", component: Honest.FirewallPolicies, crumbs: () => [crumb("VPC", ""), crumb("Firewall policies", "firewall-policies")] },
    { pattern: "/vpc/network-firewall-rule-groups", component: Honest.NetworkFirewallRuleGroups, crumbs: () => [crumb("VPC", ""), crumb("Network Firewall rule groups", "network-firewall-rule-groups")] },
    { pattern: "/vpc/tls-inspection-configurations", component: Honest.TlsInspectionConfigurations, crumbs: () => [crumb("VPC", ""), crumb("TLS inspection configurations", "tls-inspection-configurations")] },
    { pattern: "/vpc/network-firewall-resource-groups", component: Honest.NetworkFirewallResourceGroups, crumbs: () => [crumb("VPC", ""), crumb("Network Firewall resource groups", "network-firewall-resource-groups")] },
    { pattern: "/vpc/vpc-endpoint-associations", component: Honest.VpcEndpointAssociations, crumbs: () => [crumb("VPC", ""), crumb("VPC endpoint associations", "vpc-endpoint-associations")] },
    { pattern: "/vpc/container-associations", component: Honest.ContainerAssociations, crumbs: () => [crumb("VPC", ""), crumb("Container associations", "container-associations")] },

    { pattern: "/vpc/customer-gateways", component: Honest.CustomerGateways, crumbs: () => [crumb("VPC", ""), crumb("Customer gateways", "customer-gateways")] },
    { pattern: "/vpc/virtual-private-gateways", component: Honest.VirtualPrivateGateways, crumbs: () => [crumb("VPC", ""), crumb("Virtual private gateways", "virtual-private-gateways")] },
    { pattern: "/vpc/vpn-concentrators", component: Honest.VpnConcentrators, crumbs: () => [crumb("VPC", ""), crumb("Site-to-Site VPN Concentrators", "vpn-concentrators")] },
    { pattern: "/vpc/vpn-connections", component: Honest.VpnConnections, crumbs: () => [crumb("VPC", ""), crumb("Site-to-Site VPN connections", "vpn-connections")] },
    { pattern: "/vpc/client-vpn-endpoints", component: Honest.ClientVpnEndpoints, crumbs: () => [crumb("VPC", ""), crumb("Client VPN endpoints", "client-vpn-endpoints")] },

    { pattern: "/vpc/verified-access-instances", component: Honest.VerifiedAccessInstances, crumbs: () => [crumb("VPC", ""), crumb("Verified Access instances", "verified-access-instances")] },
    { pattern: "/vpc/verified-access-trust-providers", component: Honest.VerifiedAccessTrustProviders, crumbs: () => [crumb("VPC", ""), crumb("Verified Access trust providers", "verified-access-trust-providers")] },
    { pattern: "/vpc/verified-access-groups", component: Honest.VerifiedAccessGroups, crumbs: () => [crumb("VPC", ""), crumb("Verified Access groups", "verified-access-groups")] },
    { pattern: "/vpc/verified-access-endpoints", component: Honest.VerifiedAccessEndpoints, crumbs: () => [crumb("VPC", ""), crumb("Verified Access endpoints", "verified-access-endpoints")] },

    { pattern: "/vpc/transit-gateways", component: Honest.TransitGateways, crumbs: () => [crumb("VPC", ""), crumb("Transit gateways", "transit-gateways")] },
    { pattern: "/vpc/transit-gateway-attachments", component: Honest.TransitGatewayAttachments, crumbs: () => [crumb("VPC", ""), crumb("Transit gateway attachments", "transit-gateway-attachments")] },
    { pattern: "/vpc/transit-gateway-policy-tables", component: Honest.TransitGatewayPolicyTables, crumbs: () => [crumb("VPC", ""), crumb("Transit gateway policy tables", "transit-gateway-policy-tables")] },
    { pattern: "/vpc/transit-gateway-route-tables", component: Honest.TransitGatewayRouteTables, crumbs: () => [crumb("VPC", ""), crumb("Transit gateway route tables", "transit-gateway-route-tables")] },
    { pattern: "/vpc/transit-gateway-multicast", component: Honest.TransitGatewayMulticast, crumbs: () => [crumb("VPC", ""), crumb("Transit gateway multicast", "transit-gateway-multicast")] },
    { pattern: "/vpc/metering-policies", component: Honest.MeteringPolicies, crumbs: () => [crumb("VPC", ""), crumb("Metering policies", "metering-policies")] },

    { pattern: "/vpc/mirror-sessions", component: Honest.MirrorSessions, crumbs: () => [crumb("VPC", ""), crumb("Mirror sessions", "mirror-sessions")] },
    { pattern: "/vpc/mirror-targets", component: Honest.MirrorTargets, crumbs: () => [crumb("VPC", ""), crumb("Mirror targets", "mirror-targets")] },
    { pattern: "/vpc/mirror-filters", component: Honest.MirrorFilters, crumbs: () => [crumb("VPC", ""), crumb("Mirror filters", "mirror-filters")] },

    { pattern: "/vpc/settings", component: Settings, crumbs: () => [crumb("VPC", ""), crumb("Settings", "settings")] },
  ],
};
