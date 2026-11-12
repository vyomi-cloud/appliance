/* Queue Monitoring: historical AWS/SQS CloudWatch metrics over the native CloudWatch wire. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { awsJson } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { LineChart } from "../cloudwatch/common.jsx";

const METRICS = [
  ["NumberOfMessagesSent", "Number of messages sent", "Sum"],
  ["NumberOfMessagesReceived", "Number of messages received", "Sum"],
  ["NumberOfMessagesDeleted", "Number of messages deleted", "Sum"],
  ["ApproximateNumberOfMessagesVisible", "Approximate number of messages visible", "Maximum"],
  ["ApproximateNumberOfMessagesNotVisible", "Approximate number of messages not visible", "Maximum"],
  ["ApproximateAgeOfOldestMessage", "Approximate age of oldest message (seconds)", "Maximum"],
  ["SentMessageSize", "Sent message size (bytes)", "Sum"],
  ["NumberOfEmptyReceives", "Number of empty receives", "Sum"],
];

async function series(queue, metric, stat) {
  const end = new Date(), start = new Date(end - 3 * 3600_000);
  const r = await awsJson("monitoring", "GraniteServiceVersion20100801.GetMetricStatistics", {
    Namespace: "AWS/SQS", MetricName: metric, Dimensions: [{ Name: "QueueName", Value: queue }],
    StartTime: start.toISOString(), EndTime: new Date(+end + 60_000).toISOString(), Period: 60, Statistics: [stat],
  });
  return (r.Datapoints || []).map((p) => ({ t: new Date(p.Timestamp).getTime(), v: Number(p[stat]) })).sort((a, b) => a.t - b.t);
}

export default function QueueMetrics({ queue }) {
  const m = useAsync(async () => {
    const out = [];
    for (const [id, label, stat] of METRICS) out.push({ id, label, pts: await series(queue, id, stat) });
    return out;
  }, [queue]);
  return (
    <CapabilityContainer id="sqs.queue.metrics" title="Historical CloudWatch metrics" description="Last 3 hours, one-minute periods."
      actions={<Button iconName="refresh" onClick={m.reload}>Refresh</Button>}>
      {m.loading ? <StatusIndicator type="loading">Loading</StatusIndicator> : m.error ? <ErrorAlert error={m.error} /> : (
        <SpaceBetween size="l">
          {m.data.map((x) => (
            <SpaceBetween key={x.id} size="xxs">
              <Box variant="h3">{x.label}</Box>
              <Box variant="small" color="text-body-secondary">Latest: <span data-testid={`sqs-metric-${x.id}`}>{x.pts.length ? x.pts[x.pts.length - 1].v : "no data"}</span></Box>
              <LineChart series={x.pts} height={120} />
            </SpaceBetween>
          ))}
        </SpaceBetween>
      )}
    </CapabilityContainer>
  );
}
