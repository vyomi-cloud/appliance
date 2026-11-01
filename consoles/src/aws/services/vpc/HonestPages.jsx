/* Pages the real VPC console declares that are each a separate, large AWS service surfaced
 * under the VPC nav (Lattice, Network Firewall, DNS firewall, Site-to-Site VPN, Transit
 * Gateway, Traffic Mirroring) — out of scope for vpc_core.py's VPC/subnet/route-table/
 * security-group/NACL network-simulation model. Each renders ONLY its title + an honest gap
 * panel, same as ec2/HonestPages.jsx. Flagged in spec-map.json as honest_page for orchestrator
 * allowlist review (none of these are in consoles/honest-allowlist.json yet). PrivateLink and
 * Verified Access moved out of this file — they're real now (Endpoints.jsx / VerifiedAccess.jsx). */
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const page = (title, id) => () => (
  <ContentLayout header={<Header variant="h1">{title}</Header>}>
    <CapabilityContainer id={id} title={title} />
  </ContentLayout>
);

// Network Access Analyzer, PrivateLink getting-started/Endpoints/Endpoint services, and
// Verified Access (instances/trust providers/groups/endpoints) are real now — see
// NetworkAccessAnalyzer.jsx, Endpoints.jsx, VerifiedAccess.jsx — removed from this honest list.

// Lattice (service mesh — separate control plane from vpc_core.py's VPC/subnet/route-table model)
export const ServiceNetworks = page("Service networks", "aws.vpc.lattice");
export const LatticeServices = page("Lattice services", "aws.vpc.lattice");
export const ResourceConfigurations = page("Resource configurations", "aws.vpc.lattice");
export const ResourceGateways = page("Resource gateways", "aws.vpc.lattice");
export const LatticeTargetGroups = page("Target groups", "aws.vpc.lattice");
export const DomainVerifications = page("Domain verifications", "aws.vpc.lattice");

// DNS firewall
export const DnsFirewallRuleGroups = page("Rule groups", "aws.vpc.dns-firewall");
export const DnsFirewallDomainLists = page("Domain lists", "aws.vpc.dns-firewall");

// Network Firewall
export const Firewalls = page("Firewalls", "aws.vpc.network-firewall");
export const FirewallPolicies = page("Firewall policies", "aws.vpc.network-firewall");
export const NetworkFirewallRuleGroups = page("Network Firewall rule groups", "aws.vpc.network-firewall");
export const TlsInspectionConfigurations = page("TLS inspection configurations", "aws.vpc.network-firewall");
export const NetworkFirewallResourceGroups = page("Network Firewall resource groups", "aws.vpc.network-firewall");
export const VpcEndpointAssociations = page("VPC endpoint associations", "aws.vpc.network-firewall");
export const ContainerAssociations = page("Container associations", "aws.vpc.network-firewall");

// Site-to-Site VPN / Client VPN
export const CustomerGateways = page("Customer gateways", "aws.vpc.vpn");
export const VirtualPrivateGateways = page("Virtual private gateways", "aws.vpc.vpn");
export const VpnConcentrators = page("Site-to-Site VPN Concentrators", "aws.vpc.vpn");
export const VpnConnections = page("Site-to-Site VPN connections", "aws.vpc.vpn");
export const ClientVpnEndpoints = page("Client VPN endpoints", "aws.vpc.vpn");

// Transit gateways
export const TransitGateways = page("Transit gateways", "aws.vpc.transit-gateway");
export const TransitGatewayAttachments = page("Transit gateway attachments", "aws.vpc.transit-gateway");
export const TransitGatewayPolicyTables = page("Transit gateway policy tables", "aws.vpc.transit-gateway");
export const TransitGatewayRouteTables = page("Transit gateway route tables", "aws.vpc.transit-gateway");
export const TransitGatewayMulticast = page("Transit gateway multicast", "aws.vpc.transit-gateway");
export const MeteringPolicies = page("Metering policies", "aws.vpc.transit-gateway");

// Traffic Mirroring
export const MirrorSessions = page("Mirror sessions", "aws.vpc.traffic-mirroring");
export const MirrorTargets = page("Mirror targets", "aws.vpc.traffic-mirroring");
export const MirrorFilters = page("Mirror filters", "aws.vpc.traffic-mirroring");
