/* "All VPC Resources" — resource counts per Region. Vyomi simulates exactly one Region, so the summary is
 * computed from live describe calls for us-east-1 and says so for every other Region (no invented counts). */
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Alert from "@cloudscape-design/components/alert";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const KINDS = [
  ["VPCs", () => api.describeVpcs()], ["Subnets", () => api.describeSubnets()], ["Route tables", () => api.describeRouteTables()],
  ["Internet gateways", () => api.describeInternetGateways()], ["Egress-only internet gateways", () => api.describeEgressOnlyInternetGateways()],
  ["DHCP option sets", () => api.describeDhcpOptions()], ["Elastic IPs", () => api.describeAddresses()], ["NAT gateways", () => api.describeNatGateways()],
  ["VPC peering connections", () => api.describeVpcPeeringConnections()], ["Network ACLs", () => api.describeNetworkAcls()],
  ["Security groups", () => api.describeSecurityGroups()], ["Network interfaces", () => api.describeNetworkInterfaces()],
  ["VPC endpoints", () => api.describeVpcEndpoints()], ["Flow logs", () => api.describeFlowLogs()], ["Transit gateways", () => api.describeTransitGateways()],
];

export default function AllResources() {
  const t = useAsync(async () => Promise.all(KINDS.map(async ([name, fn]) => { try { return { name, n: (await fn()).length }; } catch { return { name, n: null }; } })));
  const rows = t.data || [];
  return (
    <ContentLayout header={<Header variant="h1" description="Resources in your account by Region." actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />}>All VPC resources</Header>}>
      <SpaceBetween size="l">
        <Alert type="info" header="One simulated Region">Vyomi simulates a single Region (us-east-1). Other Regions are not modeled, so they have no resources to list.</Alert>
        <Table variant="container" loading={t.loading} items={rows} trackBy="name"
          header={<Header variant="h2" counter={`(${rows.length})`}>US East (N. Virginia) us-east-1</Header>}
          columnDefinitions={[{ id: "n", header: "Resource", cell: (r) => r.name }, { id: "c", header: "Count", cell: (r) => (r.n == null ? "-" : r.n) }]}
          empty={<Box textAlign="center" color="inherit">No data</Box>} />
      </SpaceBetween>
    </ContentLayout>
  );
}
