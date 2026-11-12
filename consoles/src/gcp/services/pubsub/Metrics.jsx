/* Metrics tab: real Cloud Monitoring series read back over the native timeSeries API,
 * fed by core/gcp_pubsub_core.py's _sync_topic_metrics / _sync_subscription_metrics from
 * the core's OWN activity — never synthetic data (see core/capabilities/gcp/pubsub.json). */
import { Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function Sparkline({ points }) {
  const vals = points.map(api.pointValue).slice().reverse();   // the API returns newest-first
  if (!vals.length) return null;
  const min = Math.min(...vals), max = Math.max(...vals);
  const norm = (v) => (max === min ? 20 : 40 - ((v - min) / (max - min)) * 40);
  const d = vals.map((v, i) => `${i === 0 ? "M" : "L"} ${(i / Math.max(vals.length - 1, 1)) * 160} ${norm(v)}`).join(" ");
  return <svg width={160} height={40} aria-hidden><path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} /></svg>;
}

function Stat({ label, points, unit }) {
  const latest = points.length ? api.pointValue(points[0]) : null;
  return (
    <Stack spacing={0.5}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h3" component="div">{latest === null ? "—" : `${latest}${unit || ""}`}</Typography>
      {points.length ? <Sparkline points={points} /> : <Typography variant="body2" color="text.secondary">No data points yet.</Typography>}
    </Stack>
  );
}

export function TopicMetrics({ id }) {
  const { data } = useAsync(() => api.topicMetrics(id), [id]);
  return (
    <CapabilityContainer id="gcp.pubsub.metrics" title="Metrics">
      <Stack direction="row" spacing={5}>
        <Stat label="Publish message operation count (cumulative)" points={data?.published || []} />
      </Stack>
    </CapabilityContainer>
  );
}

export function SubscriptionMetrics({ id }) {
  const { data } = useAsync(() => api.subscriptionMetrics(id), [id]);
  return (
    <CapabilityContainer id="gcp.pubsub.metrics" title="Metrics">
      <Stack direction="row" spacing={5}>
        <Stat label="Unacked messages" points={data?.backlog || []} />
        <Stat label="Oldest unacked message age" points={data?.oldest || []} unit="s" />
      </Stack>
    </CapabilityContainer>
  );
}
