/* Live "Service health" for a service page: runs real probes against THIS environment's APIs (latency, resource states,
 * sync states) and reports what it finds. There is no incident feed: Vyomi never invents incidents, and AWS's real
 * status page (health.aws.amazon.com) is linked for the real cloud. Each probe is { name, run: async () => ({ ok, detail }) }. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../common/useAsync.js";
import { ErrorAlert } from "./common.jsx";

/** Runs the probes in parallel; a throwing probe is a failed check (with its message), never a crashed page. */
export async function runProbes(probes) {
  return Promise.all(probes.map(async (p) => {
    const t0 = performance.now();
    try {
      const r = await p.run();
      return { name: p.name, ok: !!r.ok, detail: r.detail, ms: Math.round(performance.now() - t0) };
    } catch (e) {
      return { name: p.name, ok: false, detail: `Probe failed: ${e?.message || e}`, ms: Math.round(performance.now() - t0) };
    }
  }));
}

export function HealthSummary({ results }) {
  const ok = results && results.every((r) => r.ok);
  return <StatusIndicator type={!results ? "loading" : ok ? "success" : "warning"}>{!results ? "Checking" : ok ? "Service is operating normally" : "Some checks need attention"}</StatusIndicator>;
}

export default function ServiceHealthPage({ title, service, probes, statusUrl = "https://health.aws.amazon.com/health/status" }) {
  const t = useAsync(() => runProbes(probes), []);
  return (
    <ContentLayout header={<Header variant="h1" description={`Live checks of ${service} in this Vyomi environment.`}>{title}</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<Button iconName="refresh" ariaLabel="Refresh service health" onClick={t.reload}>Refresh</Button>}>Current status</Header>}>
          {t.error ? <ErrorAlert error={t.error} /> : <HealthSummary results={t.data} />}
        </Container>
        <Table variant="container" header={<Header variant="h2">Health checks</Header>} loading={t.loading} items={t.data || []} trackBy="name"
          columnDefinitions={[
            { id: "n", header: "Check", cell: (r) => r.name, isRowHeader: true },
            { id: "s", header: "Status", cell: (r) => <StatusIndicator type={r.ok ? "success" : "warning"}>{r.ok ? "Healthy" : "Needs attention"}</StatusIndicator> },
            { id: "d", header: "Details", cell: (r) => r.detail },
            { id: "m", header: "Probe time", cell: (r) => `${r.ms} ms` },
          ]}
          empty={<Box textAlign="center" color="inherit">No checks.</Box>} />
        <Box variant="small" color="text-body-secondary">
          These are probes of your local environment; Vyomi has no incident feed and reports no incidents it did not observe. For the real cloud, see the <Link external href={statusUrl}>AWS Health Dashboard</Link>.
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
