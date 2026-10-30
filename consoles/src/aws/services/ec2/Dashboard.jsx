import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Container from "@cloudscape-design/components/container";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Grid from "@cloudscape-design/components/grid";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Dashboard() {
  const t = useAsync(() => Promise.all([
    api.describeInstances(), api.describeVolumes(), api.describeSnapshots(), api.describeSecurityGroups(),
    api.describeKeyPairs(), api.describeAddresses(), api.describePlacementGroups(),
  ]).then(([instances, volumes, snapshots, sgs, keyPairs, addresses, pgs]) => ({ instances, volumes, snapshots, sgs, keyPairs, addresses, pgs })), []);
  const d = t.data || { instances: [], volumes: [], snapshots: [], sgs: [], keyPairs: [], addresses: [], pgs: [] };
  const running = d.instances.filter((i) => i.instanceState?.name === "running").length;

  return (
    <ContentLayout header={<Header variant="h1" actions={<Button href={href("ec2", "settings")} onFollow={follow}>Settings</Button>}>Dashboard</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />}>Resources</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            {[
              ["Instances (running)", running], ["Instances", d.instances.length], ["Volumes", d.volumes.length],
              ["Snapshots", d.snapshots.length], ["Security groups", d.sgs.length], ["Key pairs", d.keyPairs.length],
              ["Elastic IPs", d.addresses.length], ["Placement groups", d.pgs.length],
              ["Load balancers", 0], ["Auto Scaling Groups", 0], ["Capacity Reservations", 0], ["Dedicated Hosts", 0],
            ].map(([label, value]) => (
              <div key={label}><Box variant="awsui-key-label">{label}</Box><div>{value}</div></div>
            ))}
          </ColumnLayout>
        </Container>

        <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
          <Container header={<Header variant="h2">Launch instance</Header>}>
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="primary" href={href("ec2", "launch-instance")} onFollow={follow}>Launch instance</Button>
              <Button href={href("ec2", "migrate-a-server")} onFollow={follow}>Migrate a server</Button>
            </SpaceBetween>
          </Container>
          <NotSimulatedContainer title="Service health" feature="AWS Health Dashboard" note="Region-wide service health events aren't modeled by Vyomi." />
        </Grid>

        <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
          <NotSimulatedContainer title="Zones" feature="Local Zones / Wavelength Zones enablement" />
          <NotSimulatedContainer title="Instance alarms" feature="CloudWatch alarms" note="No custom alarms are modeled by Vyomi." />
        </Grid>

        <NotSimulatedContainer title="EC2 cost" feature="AWS Cost Explorer" note="Cost and usage data isn't modeled by Vyomi." />
      </SpaceBetween>
    </ContentLayout>
  );
}
