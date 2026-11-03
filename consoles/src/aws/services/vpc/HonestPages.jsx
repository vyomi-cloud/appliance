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
export const ContainerAssociations = page("Container associations", "aws.vpc.network-firewall-containers");

// Site-to-Site VPN / Client VPN

// Transit gateways
export const TransitGateways = page("Transit gateways", "aws.vpc.transit-gateway");
export const TransitGatewayAttachments = page("Transit gateway attachments", "aws.vpc.transit-gateway");
export const TransitGatewayRouteTables = page("Transit gateway route tables", "aws.vpc.transit-gateway");

// Traffic Mirroring
