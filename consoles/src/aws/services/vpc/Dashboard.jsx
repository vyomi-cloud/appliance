import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import { useAsync } from "../../../common/useAsync.js";
import { href, follow } from "../../../common/router.js";
import { HealthSummary, runProbes } from "../../kit/ServiceHealth.jsx";
import { probes } from "./ServiceHealth.jsx";
import * as api from "./api.js";

const counter = (label, n, reload) => (
  <div key={label}>
    <Box variant="awsui-key-label">{label}</Box>
    <SpaceBetween direction="horizontal" size="xs" alignItems="center">
      <Box fontSize="heading-l">{n}</Box>
      <Link onFollow={reload}>See all regions</Link>
    </SpaceBetween>
  </div>
);

export default function Dashboard() {
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const subnets = useAsync(() => api.describeSubnets(), []);
  const rts = useAsync(() => api.describeRouteTables(), []);
  const igws = useAsync(() => api.describeInternetGateways(), []);
  const eigws = useAsync(() => api.describeEgressOnlyInternetGateways(), []);
  const dopts = useAsync(() => api.describeDhcpOptions(), []);
  const eips = useAsync(() => api.describeAddresses(), []);
  const nats = useAsync(() => api.describeNatGateways(), []);
  const pcxs = useAsync(() => api.describeVpcPeeringConnections(), []);
  const nacls = useAsync(() => api.describeNetworkAcls(), []);
  const sgs = useAsync(() => api.describeSecurityGroups(), []);
  const health = useAsync(() => runProbes(probes), []);
  const reloadAll = () => { vpcs.reload(); subnets.reload(); rts.reload(); igws.reload(); eigws.reload(); dopts.reload(); eips.reload(); nats.reload(); pcxs.reload(); nacls.reload(); sgs.reload(); };

  const rows = [
    ["VPCs", vpcs.data?.length ?? "-"], ["Subnets", subnets.data?.length ?? "-"], ["Route Tables", rts.data?.length ?? "-"],
    ["Internet Gateways", igws.data?.length ?? "-"], ["Egress-only Internet Gateways", eigws.data?.length ?? "-"],
    ["DHCP option sets", dopts.data?.length ?? "-"], ["Elastic IPs", eips.data?.length ?? "-"],
    ["Endpoint Services", 0], ["NAT Gateways", nats.data?.length ?? "-"], ["VPC Peering Connections", pcxs.data?.length ?? "-"],
    ["Network ACLs", nacls.data?.length ?? "-"], ["Security Groups", sgs.data?.length ?? "-"],
    ["Customer Gateways", 0], ["Virtual Private Gateways", 0],
  ];

  return (
    <ContentLayout header={
      <Header variant="h1" actions={<SpaceBetween direction="horizontal" size="xs">
        <Button href={href("ec2", "launch-instance")} onFollow={follow}>Launch EC2 Instances</Button>
        <Button variant="primary" href={href("vpc", "create-vpc")} onFollow={follow}>Create VPC</Button>
      </SpaceBetween>}>VPC dashboard</Header>
    }>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<Button iconName="refresh" onClick={reloadAll}>Refresh Resources</Button>}>Resources by Region</Header>}>
          <ColumnLayout columns={4} variant="text-grid">{rows.map(([label, n]) => counter(label, n, reloadAll))}</ColumnLayout>
        </Container>
        <Container header={<Header variant="h2">Service Health</Header>}>
          <SpaceBetween size="s">
            <HealthSummary results={health.data} />
            <Button href={href("vpc", "service-health")} onFollow={follow}>View complete service health details</Button>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Settings</Header>}>
          <SpaceBetween direction="horizontal" size="l">
            <Button href={href("vpc", "encryption-control")} onFollow={follow}>Account-level encryption control</Button>
            <Button href={href("vpc", "settings")} onFollow={follow}>Block Public Access</Button>
            <Button href={href("vpc", "settings")} onFollow={follow}>Zones</Button>
            <Button href={href("vpc", "settings")} onFollow={follow}>Console Experiments</Button>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Additional Information</Header>}>
          <SpaceBetween direction="horizontal" size="l">
            <Button href="https://docs.aws.amazon.com/vpc/" target="_blank" iconAlign="right" iconName="external">VPC Documentation</Button>
            <Button href={href("vpc", "all-resources")} onFollow={follow}>All VPC Resources</Button>
            <Button href="https://repost.aws/tags/TA4IvCeWI1TE66q4jEj4Z9zg/amazon-virtual-private-cloud" target="_blank" iconAlign="right" iconName="external">Forums</Button>
            <Button href="https://github.com/vyomi-cloud/appliance/issues/new" target="_blank" iconAlign="right" iconName="external">Report an Issue</Button>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">AWS Network Manager</Header>}>
          <Button href="#/networkmanager/global-networks" onFollow={follow}>Open Network Manager</Button>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
