import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Container from "@cloudscape-design/components/container";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import Grid from "@cloudscape-design/components/grid";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { statusOf } from "./Tables.jsx";
import { getFavoriteTables } from "./prefs.js";
import * as api from "./api.js";

const ALARM_STATE = {
  ALARM: <StatusIndicator type="error">In alarm</StatusIndicator>,
  OK: <StatusIndicator type="success">OK</StatusIndicator>,
  INSUFFICIENT_DATA: <StatusIndicator type="pending">Insufficient data</StatusIndicator>,
};
const tableOf = (a) => ((a.Dimensions || []).find((x) => x.Name === "TableName") || {}).Value;

export default function Dashboard() {
  const alarms = useAsync(() => api.describeDynamoDbAlarms(), []);
  const clusters = useAsync(() => api.describeDaxClusters(), []);
  const inAlarm = (alarms.data || []).filter((a) => a.StateValue === "ALARM").length;
  const favorites = useAsync(async () => {
    const names = getFavoriteTables();
    return Promise.all(names.map((n) => api.describeTable(n).catch(() => null))).then((rows) => rows.filter(Boolean));
  }, []);

  return (
    <ContentLayout header={<Header variant="h1">Dashboard</Header>}>
      <SpaceBetween size="l">
        <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
          <Table
            variant="container"
            items={alarms.data || []}
            loading={alarms.loading}
            loadingText="Loading alarms"
            header={<Header variant="h2" counter={alarms.data ? `(${inAlarm} in alarm / ${alarms.data.length})` : undefined}
              actions={<Button href="#/cloudwatch/alarms" onFollow={follow}>View in CloudWatch</Button>}>Alarms</Header>}
            columnDefinitions={[
              { id: "name", header: "Name", cell: (a) => <Link href={`#/cloudwatch/alarms/${encodeURIComponent(a.AlarmName)}`} onFollow={follow}>{a.AlarmName}</Link> },
              { id: "state", header: "State", cell: (a) => ALARM_STATE[a.StateValue] || a.StateValue },
              { id: "table", header: "Table", cell: (a) => tableOf(a) ? <Link href={href("dynamodb", "tables", tableOf(a))} onFollow={follow}>{tableOf(a)}</Link> : "-" },
              { id: "metric", header: "Metric", cell: (a) => a.MetricName },
            ]}
            empty={<Box textAlign="center" color="inherit">
              <b>No alarms</b>
              <Box variant="p" color="inherit">Create one from a table's Monitor tab.</Box>
            </Box>}
          />
          <Container header={<Header variant="h2">Create resources</Header>}>
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="primary" href={href("dynamodb", "create-table")} onFollow={follow}>Create table</Button>
              <Button href={href("dynamodb", "dax", "clusters")} onFollow={follow}>Create DAX cluster</Button>
            </SpaceBetween>
          </Container>
        </Grid>

        <Table
          variant="container"
          items={favorites.data || []}
          loading={favorites.loading}
          header={<Header variant="h2" counter={`(${(favorites.data || []).length})`} actions={<Button href={href("dynamodb", "tables")} onFollow={follow}>View all tables</Button>}>Favorite tables</Header>}
          columnDefinitions={[
            { id: "name", header: "Table name", cell: (t) => <Link href={href("dynamodb", "tables", t.TableName)} onFollow={follow}>{t.TableName}</Link> },
            { id: "status", header: "Status", cell: (t) => statusOf(t.TableStatus) },
            { id: "created", header: "Created at (UTC)", cell: (t) => t.CreationDateTime || "-" },
          ]}
          empty={<Box textAlign="center" color="inherit">
            <b>No favorite tables</b>
            <Box variant="p" color="inherit">Star a table from the Tables list to pin it here.</Box>
          </Box>}
        />

        <Table
          variant="container"
          items={clusters.data || []}
          loading={clusters.loading}
          loadingText="Loading DAX clusters"
          header={<Header variant="h2" counter={`(${(clusters.data || []).length})`}
            actions={<Button href={href("dynamodb", "dax", "clusters")} onFollow={follow}>View all clusters</Button>}>DAX clusters</Header>}
          columnDefinitions={[
            { id: "name", header: "Cluster name", cell: (c) => c.ClusterName },
            { id: "status", header: "Status", cell: (c) => c.Status },
            { id: "nodes", header: "Nodes", cell: (c) => c.TotalNodes ?? (c.Nodes || []).length },
            { id: "type", header: "Node type", cell: (c) => c.NodeType },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No DAX clusters</b></Box>}
        />

        <Container header={<Header variant="h2">What's new</Header>}>
          <SpaceBetween size="s">
            <Box variant="p">PartiQL editor, on-demand and continuous backups, and Time to Live are now backed by Vyomi — try them from the navigation on the left.</Box>
            <Box variant="p">Star a table from the Tables list to see it under Favorite tables here.</Box>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
