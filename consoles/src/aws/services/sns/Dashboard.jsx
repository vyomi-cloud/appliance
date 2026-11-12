import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Grid from "@cloudscape-design/components/grid";
import { useAsync } from "../../../common/useAsync.js";
import { KeyValue } from "../../kit/common.jsx";
import { getRegion } from "../../../common/wire.js";
import * as api from "./api.js";

export default function Dashboard() {
  const counts = useAsync(async () => {
    const [topics, apps, subs] = await Promise.all([api.listTopics(), api.listPlatformApplications(), api.listSubscriptions()]);
    return { topics: topics.length, apps: apps.length, subs: subs.length };
  }, []);
  const c = counts.data || { topics: 0, apps: 0, subs: 0 };

  return (
    <ContentLayout header={<Header variant="h1">Dashboard</Header>}>
      <SpaceBetween size="l">
        <KeyValue title={`Resources for ${getRegion()}`} columns={3} items={[
          ["Topics", c.topics], ["Platform applications", c.apps], ["Subscriptions", c.subs],
        ]} />
        <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
          <KeyValue title="Overview of Amazon SNS" columns={1} items={[
            ["Application-to-application (A2A)", "Pub/sub messaging between topics and SQS queues, Lambda functions, and HTTP/S endpoints."],
          ]} />
          <KeyValue title=" " columns={1} items={[
            ["Application-to-person (A2P)", "Direct messaging to mobile devices (push), SMS text messages, and email."],
          ]} />
        </Grid>
      </SpaceBetween>
    </ContentLayout>
  );
}
