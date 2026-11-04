import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Box from "@cloudscape-design/components/box";
import Link from "@cloudscape-design/components/link";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import * as api from "./api.js";

export default function Dashboard() {
  const t = useAsync(async () => {
    const [instances, snapshots, events] = await Promise.all([
      api.describeDBInstances(), api.describeDBSnapshots(), api.describeEvents(),
    ]);
    return { instances, snapshots, events };
  });
  const n = (xs) => (xs ? xs.length : 0);

  return (
    <ContentLayout header={<Header variant="h1">Welcome to Aurora and RDS</Header>}>
      <SpaceBetween size="l">
        <ColumnLayout columns={2}>
          <Container header={<Header variant="h2" actions={<Button variant="primary" href={href("rds", "create-database")} onFollow={follow}>Create</Button>}>
            Create with express configuration in seconds</Header>}>
            Launch a database in a few clicks with recommended best-practice defaults.
          </Container>
          <Container header={<Header variant="h2" actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button href={href("rds", "restore-from-s3")} onFollow={follow}>Restore from S3</Button>
              <Button variant="primary" href={href("rds", "create-database")} onFollow={follow}>Create</Button>
            </SpaceBetween>
          }>Create with full configuration</Header>}>
            Configure every setting of your database yourself.
          </Container>
        </ColumnLayout>

        <Container header={<Header variant="h2" actions={<Button href="#/rds/service-quota">View service quota</Button>}>Service overview</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            <div><Box variant="awsui-key-label">DB clusters</Box><div>0</div></div>
            <div><Box variant="awsui-key-label">DB instances</Box><div>{n(t.data?.instances)}</div></div>
            <div><Box variant="awsui-key-label">Snapshots</Box><div>{n(t.data?.snapshots)}</div></div>
            <div><Box variant="awsui-key-label">Recent events</Box><div>{n(t.data?.events)}</div></div>
          </ColumnLayout>
        </Container>

        <Table variant="container" items={[{ status: "Operating normally", details: "All RDS systems are operating normally." }]}
          header={<Header variant="h2" actions={<Button href="#/rds/service-health">View service health dashboard</Button>}>Service health</Header>}
          columnDefinitions={[{ id: "s", header: "Current status", cell: (r) => r.status }, { id: "d", header: "Details", cell: (r) => r.details }]} />

        <Container header={<Header variant="h2" actions={<Button>Start tutorial</Button>}>Explore Aurora & RDS</Header>}>
          Learn how to create and connect to an Amazon Aurora or RDS database.
        </Container>

        <Container header={<Header variant="h2">RDS costs</Header>}>
          <Link href="#/cost-explorer">View your RDS costs in Cost Explorer</Link>
        </Container>

        <Container header={<Header variant="h2">Additional information</Header>}>
          <SpaceBetween size="xs">
            <Link external href="https://docs.aws.amazon.com/rds/">Amazon RDS documentation</Link>
            <Link href={href("rds", "query-editor")} onFollow={follow}>Query editor</Link>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
