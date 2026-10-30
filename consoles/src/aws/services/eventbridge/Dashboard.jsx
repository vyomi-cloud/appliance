import Box from "@cloudscape-design/components/box";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

function Stat({ label, value }) {
  return <div><Box variant="awsui-key-label">{label}</Box><Box fontSize="display-l">{value ?? "–"}</Box></div>;
}

function QuotaNote({ title, lines }) {
  return (
    <Container header={<Header variant="h2">{title}</Header>}>
      <SpaceBetween size="xs">
        {lines.map((l) => <Box key={l} variant="small" color="text-body-secondary">{l}</Box>)}
      </SpaceBetween>
    </Container>
  );
}

export default function Dashboard() {
  const { data } = useAsync(async () => {
    const buses = await api.listEventBuses();
    const custom = buses.filter((b) => b.Name !== "default");
    const [defaultRules, groups, schedules] = await Promise.all([
      api.listRules("default"), api.listScheduleGroups(), api.listSchedules(),
    ]);
    return { buses: buses.length, custom: custom.length, rules: defaultRules.length, groups: groups.length, schedules: schedules.length };
  });
  const d = data || {};

  return (
    <ContentLayout header={<Header variant="h1">Dashboard</Header>}>
      <Tabs tabs={[
        {
          id: "custom", label: "Custom event buses - new", content: (
            <SpaceBetween size="l">
              <Container header={<Header variant="h2">Resources</Header>}>
                <ColumnLayout columns={2} variant="text-grid">
                  <Stat label="Buses" value={d.custom} />
                  <Stat label="Subscribers" value={d.rules} />
                </ColumnLayout>
              </Container>
              <NotSimulatedContainer title="Account-level metrics" note="CloudWatch metrics for EventBridge aren't aggregated in Vyomi." />
              <QuotaNote title="Service quotas for Custom event buses" lines={["Custom event buses per account — AWS default quota value: 100 (adjustable).", "Rules per event bus — AWS default quota value: 300 (adjustable)."]} />
            </SpaceBetween>
          ),
        },
        {
          id: "classic", label: "Classic & Default bus", content: (
            <SpaceBetween size="l">
              <Container header={<Header variant="h2">Resources</Header>}>
                <ColumnLayout columns={3} variant="text-grid">
                  <Stat label="Buses" value={d.buses} />
                  <Stat label="Rules" value={d.rules} />
                  <Stat label="API destinations" value={0} />
                </ColumnLayout>
              </Container>
              <NotSimulatedContainer title="Account-level metrics" note="CloudWatch metrics for EventBridge aren't aggregated in Vyomi." />
              <NotSimulatedContainer title="Resource-level metrics" note="Per-rule CloudWatch metrics aren't aggregated in Vyomi." />
              <QuotaNote title="Service quotas for Event buses" lines={["Event buses per account — AWS default quota value: 100 (adjustable)."]} />
            </SpaceBetween>
          ),
        },
        {
          id: "pipes", label: "Pipes", content: (
            <SpaceBetween size="l">
              <Container header={<Header variant="h2">Resources</Header>}><ColumnLayout columns={1} variant="text-grid"><Stat label="Pipes" value={0} /></ColumnLayout></Container>
              <NotSimulatedContainer title="Account-level metrics" />
              <NotSimulatedContainer title="Resource-level metrics" />
            </SpaceBetween>
          ),
        },
        {
          id: "scheduler", label: "Scheduler", content: (
            <SpaceBetween size="l">
              <Container header={<Header variant="h2">Resources</Header>}><ColumnLayout columns={1} variant="text-grid"><Stat label="Schedule groups" value={d.groups} /></ColumnLayout></Container>
              <NotSimulatedContainer title="Account-level metrics" note="CloudWatch metrics for Scheduler aren't aggregated in Vyomi." />
              <QuotaNote title="Service quotas for Scheduler" lines={[`Schedules per account — AWS default quota value: 1,000,000 (adjustable). Currently: ${d.schedules ?? "–"}.`]} />
            </SpaceBetween>
          ),
        },
      ]} />
    </ContentLayout>
  );
}
