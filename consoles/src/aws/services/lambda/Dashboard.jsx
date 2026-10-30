/* Dashboard — real counts and code-storage size computed from the live function store
 * (ListFunctions + per-function Function URL lookups), not static placeholders. */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import { getRegion } from "../../../common/wire.js";
import { follow } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, fmtBytes, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const ACCOUNT_LIMIT = 1000;
const CODE_STORAGE_CAP = 300 * 1024 * 1024 * 1024; // 300 GB, the real Lambda account default

function Placeholder({ title }) {
  return <Container header={<Header variant="h2">{title}</Header>}><Box variant="p" color="text-body-secondary">No data yet — create a function to see metrics here.</Box></Container>;
}

export default function Dashboard() {
  const t = useAsync(() => api.listFunctionsSplit(), []);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const { eventFunctions, webFunctions } = t.data;
  const codeSize = [...eventFunctions, ...webFunctions].reduce((a, f) => a + (f.CodeSize || 0), 0);
  const reserved = [...eventFunctions, ...webFunctions].reduce((a, f) => a + (f.ReservedConcurrentExecutions || 0), 0);

  return (
    <ContentLayout header={<Header variant="h1">Dashboard</Header>}>
      <SpaceBetween size="l">
        <NotSimulatedContainer title="Set up your agent to build with Lambda" feature="Lambda's AI coding-agent onboarding (MCP server + agent prompt)" />

        <Tabs tabs={[
          {
            id: "event", label: "Event Functions", content: (
              <SpaceBetween size="l">
                <KeyValue title={`Resources for ${getRegion()}`} actions={<Button variant="primary" href="#/lambda/create/function" onFollow={follow}>Create Event Function</Button>}
                  columns={4} items={[
                    ["Lambda Event Function(s)", eventFunctions.length],
                    ["Code storage", `${fmtBytes(codeSize)} (${((codeSize / CODE_STORAGE_CAP) * 100).toFixed(4)}% of 300 GB)`],
                    ["Full account concurrency", ACCOUNT_LIMIT.toLocaleString()],
                    ["Unreserved account concurrency", Math.max(0, ACCOUNT_LIMIT - reserved).toLocaleString()],
                  ]} />
                <Placeholder title="Top 10 Event Functions" />
                <Placeholder title="Account-level Event Function metrics" />
              </SpaceBetween>
            ),
          },
          {
            id: "web", label: "Web Functions", content: (
              <SpaceBetween size="l">
                <Placeholder title="Top 10 Web Functions" />
                <Placeholder title="Account-level Web Functions metrics" />
                <Placeholder title="Account throttles" />
              </SpaceBetween>
            ),
          },
        ]} />

        <Container header={<Header variant="h2">Recommended for you</Header>}>
          <SpaceBetween direction="horizontal" size="l">
            <Button href="#/lambda/create/function" onFollow={follow}>Create an Event Function</Button>
            <Button href="#/lambda/layers" onFollow={follow}>Browse layers</Button>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Developer resources</Header>}>
          <Button href="#/lambda/extensions" onFollow={follow} variant="link">Extensions</Button>
        </Container>
        <Container header={<Header variant="h2">Additional information</Header>}>
          <Box variant="p" color="text-body-secondary">Lambda functions run in a sandboxed Python runtime (see core/capabilities/aws/lambda.json for exact simulation scope).</Box>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
