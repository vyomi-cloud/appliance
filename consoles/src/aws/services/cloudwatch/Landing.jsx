/* CloudWatch home. The real console's landing page loads inside an iframe the capture
 * crawler couldn't read (ui-spec notes it rendered blank); Vyomi gives it real content —
 * live counters pulled from the same alarms/dashboards/log-groups APIs the rest of the
 * service uses, not a static mock. */
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Box from "@cloudscape-design/components/box";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

function Stat({ title, value, to }) {
  return (
    <div>
      <Box variant="awsui-key-label">{title}</Box>
      <Box fontSize="display-l" fontWeight="bold">{to ? <Link href={to} onFollow={follow}>{value}</Link> : value}</Box>
    </div>
  );
}

export default function Landing() {
  const t = useAsync(async () => {
    const [alarmsRes, dashboards, groups] = await Promise.all([api.describeAlarms({}), api.listDashboards(), api.describeLogGroups({})]);
    const alarms = [...(alarmsRes.MetricAlarms || []), ...(alarmsRes.CompositeAlarms || [])];
    return { alarms, inAlarm: alarms.filter((a) => a.StateValue === "ALARM").length, dashboards, groups };
  }, []);

  return (
    <ContentLayout header={<Header variant="h1" description="Observe, monitor and act on your Vyomi resources and applications.">CloudWatch</Header>}>
      <SpaceBetween size="l">
        {t.error && <ErrorAlert error={t.error} />}
        <Container header={<Header variant="h2">Overview</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            <Stat title="Alarms in alarm" value={t.loading ? "-" : t.data.inAlarm} to={href("cloudwatch", "alarms") + "?state=ALARM"} />
            <Stat title="Total alarms" value={t.loading ? "-" : t.data.alarms.length} to={href("cloudwatch", "alarms")} />
            <Stat title="Dashboards" value={t.loading ? "-" : t.data.dashboards.length} to={href("cloudwatch", "dashboards")} />
            <Stat title="Log groups" value={t.loading ? "-" : t.data.groups.length} to={href("cloudwatch", "logs")} />
          </ColumnLayout>
        </Container>
        <ColumnLayout columns={3}>
          <Container header={<Header variant="h2">Dashboards</Header>}>
            <Box variant="p">Build custom views of the metrics that matter to you, or add widgets that graph alarms and log data.</Box>
            <Link href={href("cloudwatch", "dashboards")} onFollow={follow}>View dashboards</Link>
          </Container>
          <Container header={<Header variant="h2">Alarms</Header>}>
            <Box variant="p">Get notified automatically when a metric breaches a threshold you define.</Box>
            <Link href={href("cloudwatch", "alarms")} onFollow={follow}>View alarms</Link>
          </Container>
          <Container header={<Header variant="h2">Logs</Header>}>
            <Box variant="p">Collect, monitor and analyze log data from your applications and resources.</Box>
            <Link href={href("cloudwatch", "logs")} onFollow={follow}>View log groups</Link>
          </Container>
        </ColumnLayout>
      </SpaceBetween>
    </ContentLayout>
  );
}
