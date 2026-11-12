/* A grid of CloudWatch metric graphs for a service's Monitoring tab. Every graph is a real
 * GetMetricData call over the native wire — whatever datapoints the engine recorded are what
 * get drawn (an idle resource renders "No data points", never a synthetic line). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../common/useAsync.js";
import { LineChart, toSeries } from "../services/cloudwatch/common.jsx";
import * as cw from "../services/cloudwatch/api.js";

const RANGES = [
  { label: "Last 1 hour", value: "3600" }, { label: "Last 3 hours", value: "10800" },
  { label: "Last 1 day", value: "86400" }, { label: "Last 1 week", value: "604800" },
];

function Graph({ g, range, tick }) {
  const now = Math.floor(Date.now() / 1000);
  const period = range <= 10800 ? 60 : range <= 86400 ? 300 : 3600;
  const t = useAsync(() => cw.getMetricData(
    [{ Id: "m1", MetricStat: { Metric: { Namespace: g.namespace, MetricName: g.name, Dimensions: g.dimensions || [] }, Period: period, Stat: g.stat || "Sum" }, ReturnData: true }],
    now - range, now), [g.namespace, g.name, JSON.stringify(g.dimensions), range, tick]);
  const series = toSeries((t.data || [])[0]);
  const total = series.reduce((a, p) => a + p.v, 0);
  return (
    <div data-testid={`metric-${g.name}`}>
      <Box variant="h4">{g.title || g.name}</Box>
      {t.loading ? <Box textAlign="center" padding="l"><Spinner /></Box> : <LineChart series={series} />}
      <Box color="text-body-secondary" fontSize="body-s">{g.stat || "Sum"}{g.unit ? ` (${g.unit})` : ""}{series.length ? ` · ${series.length} datapoint${series.length === 1 ? "" : "s"} · ${g.stat === "Average" || g.stat === "Maximum" ? "latest" : "total"} ${g.stat === "Average" || g.stat === "Maximum" ? series[series.length - 1].v : total}` : ""}</Box>
    </div>
  );
}

/** graphs: [{ title, namespace, name, dimensions, stat, unit }] */
export default function MetricGraphs({ title = "Metrics", graphs, columns = 2, bare = false }) {
  const [range, setRange] = useState(RANGES[0]);
  const [tick, setTick] = useState(0);
  const controls = (
    <SpaceBetween direction="horizontal" size="xs">
      <Select selectedOption={range} onChange={({ detail }) => setRange(detail.selectedOption)} options={RANGES} />
      <Button iconName="refresh" ariaLabel="Refresh" onClick={() => setTick((n) => n + 1)} />
    </SpaceBetween>);
  const grid = (
    <ColumnLayout columns={columns}>
      {graphs.map((g) => <Graph key={g.name + JSON.stringify(g.dimensions)} g={g} range={Number(range.value)} tick={tick} />)}
    </ColumnLayout>);
  if (bare) return <SpaceBetween size="m"><Box float="right">{controls}</Box>{grid}</SpaceBetween>;
  return <Container header={<Header variant="h2" actions={controls}>{title}</Header>}>{grid}</Container>;
}
