/* Cost Explorer: "Saved by Vyomi" dashboard + Cost and usage explorer (sweep AWS-11). Every number is an estimate from on-demand list
 * prices x the real uptime of the simulator's EC2 / EBS / RDS inventory (core/ce_core.py); the simulator itself bills $0. Not an invoice. */
import { useState } from "react";
import BarChart from "@cloudscape-design/components/bar-chart";
import Box from "@cloudscape-design/components/box";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const usd = (n) => `$${Number(n || 0).toFixed(2)}`;
const iso = (d) => d.toISOString().slice(0, 10);
const RANGES = [{ value: "mtd", label: "Month to date" }, { value: "7", label: "Last 7 days" }, { value: "30", label: "Last 30 days" }];
const GROUPS = [{ value: "SERVICE", label: "Service" }, { value: "INSTANCE_TYPE", label: "Instance type" }, { value: "USAGE_TYPE", label: "Usage type" }];

function Stat({ label, value, sub, color }) {
  return (
    <div>
      <Box variant="awsui-key-label">{label}</Box>
      <Box variant="h1" color={color}>{value}</Box>
      {sub && <Box variant="small" color="text-body-secondary">{sub}</Box>}
    </div>
  );
}

function SavedByVyomi() {
  const s = useAsync(() => api.getSavings(), []);
  const d = s.data;
  return (
    <Container header={<Header variant="h2" description="What these resources would have cost on real AWS, versus the $0.00 Vyomi charged you. Estimated from list prices and real uptime; not an invoice.">Saved by Vyomi</Header>}>
      {s.error ? <ErrorAlert error={s.error} /> : !d ? <Box color="text-status-inactive">Loading...</Box> : (
        <SpaceBetween size="l">
          <ColumnLayout columns={4} variant="text-grid">
            <Stat label="Real AWS cost, month to date" value={usd(d.RealCloudCostMonthToDateUSD)} />
            <Stat label="You paid Vyomi" value={usd(d.SimulatorCostUSD)} />
            <Stat label="Saved this month" value={usd(d.SavedMonthToDateUSD)} color="text-status-success" />
            <Stat label="Saved since you started" value={usd(d.SavedLifetimeUSD)} sub={`Run rate ${usd(d.MonthlyRunRateUSD)} / month across ${d.ResourceCount} resource${d.ResourceCount === 1 ? "" : "s"}`} color="text-status-success" />
          </ColumnLayout>
          <Table variant="embedded" trackBy="ResourceId" items={(d.Resources || []).slice(0, 8)}
            header={<Header variant="h3">Biggest savers</Header>}
            columnDefinitions={[
              { id: "r", header: "Resource", cell: (r) => r.ResourceId, isRowHeader: true },
              { id: "s", header: "Service", cell: (r) => r.Service },
              { id: "t", header: "Type", cell: (r) => r.Type },
              { id: "h", header: "Hourly rate", cell: (r) => `$${r.HourlyUSD}` },
              { id: "l", header: "Saved so far", cell: (r) => usd(r.SavedLifetimeUSD) },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>Nothing metered yet</b><Box variant="p" color="inherit">Launch an EC2 instance or an RDS database and watch the savings add up.</Box></Box>} />
        </SpaceBetween>
      )}
    </Container>
  );
}

function CostAndUsage() {
  const [range, setRange] = useState(RANGES[0]);
  const [group, setGroup] = useState(GROUPS[0]);
  const q = useAsync(async () => {
    const end = new Date(); end.setUTCDate(end.getUTCDate() + 1);
    const start = new Date();
    if (range.value === "mtd") start.setUTCDate(1); else start.setUTCDate(start.getUTCDate() - Number(range.value));
    const tp = { Start: iso(start), End: iso(end) };
    const [usage, fc] = await Promise.all([
      api.getCostAndUsage({ TimePeriod: tp, Granularity: "DAILY", Metrics: ["UnblendedCost"], GroupBy: [{ Type: "DIMENSION", Key: group.value }] }),
      (async () => { try { const f = new Date(); f.setUTCDate(f.getUTCDate() + 1); const e = new Date(f); e.setUTCDate(e.getUTCDate() + 30); return await api.getCostForecast({ TimePeriod: { Start: iso(f), End: iso(e) }, Metric: "UNBLENDED_COST", Granularity: "MONTHLY" }); } catch { return null; } })(),
    ]);
    return { usage, fc };
  }, [range.value, group.value]);
  const days = q.data?.usage.ResultsByTime || [];
  const keys = [...new Set(days.flatMap((d) => d.Groups.map((g) => g.Keys[0])))];
  const series = keys.map((k) => ({ title: k, type: "bar", data: days.map((d) => ({ x: d.TimePeriod.Start.slice(5), y: Number(d.Groups.find((g) => g.Keys[0] === k)?.Metrics.UnblendedCost.Amount || 0) })) }));
  const totals = keys.map((k) => ({ key: k, total: series.find((s) => s.title === k).data.reduce((a, p) => a + p.y, 0) })).sort((a, b) => b.total - a.total);
  return (
    <Container header={<Header variant="h2" description="Daily unblended cost of the resources in your simulator (AWS-equivalent list prices)."
      actions={<SpaceBetween direction="horizontal" size="xs">
        <FormField label="Date range"><Select ariaLabel="Date range" selectedOption={range} options={RANGES} onChange={({ detail }) => setRange(detail.selectedOption)} /></FormField>
        <FormField label="Group by"><Select ariaLabel="Group by" selectedOption={group} options={GROUPS} onChange={({ detail }) => setGroup(detail.selectedOption)} /></FormField>
      </SpaceBetween>}>Cost and usage</Header>}>
      {q.error ? <ErrorAlert error={q.error} /> : (
        <SpaceBetween size="l">
          {q.data?.fc && <Box>Forecast for the next 30 days at the current run rate: <b>{usd(q.data.fc.Total.Amount)}</b></Box>}
          <BarChart series={series} xTitle="Day" yTitle="Cost (USD)" stackedBars hideFilter ariaLabel="Daily cost" height={240}
            empty={<Box textAlign="center" color="inherit"><b>No cost data</b><Box variant="p" color="inherit">No metered resources ran in this period.</Box></Box>} noMatch={<Box textAlign="center">No match</Box>} />
          <Table variant="embedded" trackBy="key" items={totals} loading={q.loading}
            columnDefinitions={[{ id: "k", header: group.label, cell: (r) => r.key, isRowHeader: true }, { id: "t", header: "Cost in period", cell: (r) => usd(r.total) }]}
            empty="No cost data" />
        </SpaceBetween>
      )}
    </Container>
  );
}

export default function CostExplorer() {
  return (
    <ContentLayout header={<Header variant="h1" description="Explore what your resources would cost on AWS. Estimates only: Vyomi does not bill you and issues no invoices.">Cost Explorer</Header>}>
      <SpaceBetween size="l">
        <SavedByVyomi />
        <CostAndUsage />
      </SpaceBetween>
    </ContentLayout>
  );
}
