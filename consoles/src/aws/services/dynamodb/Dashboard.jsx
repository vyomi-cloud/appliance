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
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { statusOf } from "./Tables.jsx";
import { getFavoriteTables } from "./prefs.js";
import * as api from "./api.js";
import { VyomiMark, vy } from "../../../common/VyomiMark.jsx";

export default function Dashboard() {
  const favorites = useAsync(async () => {
    const names = getFavoriteTables();
    return Promise.all(names.map((n) => api.describeTable(n).catch(() => null))).then((rows) => rows.filter(Boolean));
  }, []);

  return (
    <ContentLayout header={<Header variant="h1">Dashboard</Header>}>
      <SpaceBetween size="l">
        <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
          <NotSimulatedContainer title="Alarms" feature="CloudWatch alarms" note={vy("No custom alarms are modeled by Vyomi.")} />
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

        <NotSimulatedContainer title="DAX clusters" feature="DynamoDB Accelerator (DAX)" />

        <Container header={<Header variant="h2">What's new</Header>}>
          <SpaceBetween size="s">
            <Box variant="p">PartiQL editor, on-demand and continuous backups, and Time to Live are now backed by <VyomiMark /> — try them from the navigation on the left.</Box>
            <Box variant="p">Star a table from the Tables list to see it under Favorite tables here.</Box>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
