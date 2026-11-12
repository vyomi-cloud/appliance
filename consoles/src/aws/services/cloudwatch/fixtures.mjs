/* UI-conformance fixtures for CloudWatch (native GraniteServiceVersion20100801.* JSON)
 * and CloudWatch Logs (native Logs_20140328.* JSON). See s3/fixtures.mjs. */
const CW = (op) => ({ svc: "monitoring", target: `GraniteServiceVersion20100801.${op}` });
const LG = (op) => ({ svc: "logs", target: `Logs_20140328.${op}` });

export default {
  // Liveness for Dashboards / Dashboard detail: a freshly created, uniquely named dashboard.
  "live-dashboard": async (wire, uniq) => {
    const name = `uic-dash-${uniq}`;
    await wire("POST", "/", { ...CW("PutDashboard"), body: { DashboardName: name, DashboardBody: JSON.stringify({ widgets: [] }) } });
    return name;
  },
  // Liveness for Alarms / Alarm detail: a freshly created, uniquely named metric alarm.
  "live-alarm": async (wire, uniq) => {
    const name = `uic-alarm-${uniq}`;
    await wire("POST", "/", { ...CW("PutMetricAlarm"), body: {
      AlarmName: name, Namespace: "AWS/EC2", MetricName: "CPUUtilization", Statistic: "Average",
      Period: 300, Threshold: 80, ComparisonOperator: "GreaterThanThreshold", EvaluationPeriods: 1,
    } });
    return name;
  },
  // Liveness for Log management / Log group detail: a freshly created, uniquely named log group.
  "live-log-group": async (wire, uniq) => {
    const name = `uic-logs-${uniq}`;
    await wire("POST", "/", { ...LG("CreateLogGroup"), body: { logGroupName: name } });
    return name;
  },
  // Liveness for the log events page: a fixed group/stream (so the route is stable) with a
  // uniquely worded message just written into it.
  "live-log-event": async (wire, uniq) => {
    const group = "uic-log-group", stream = "uic-stream";
    await wire("POST", "/", { ...LG("CreateLogGroup"), body: { logGroupName: group } }).catch(() => {});
    await wire("POST", "/", { ...LG("CreateLogStream"), body: { logGroupName: group, logStreamName: stream } }).catch(() => {});
    const message = `live-event-${uniq}`;
    await wire("POST", "/", { ...LG("PutLogEvents"), body: { logGroupName: group, logStreamName: stream, logEvents: [{ timestamp: Date.now(), message }] } });
    return message;
  },
  // Liveness for the Metrics Browse tab: a uniquely named metric just published.
  "live-metric": async (wire, uniq) => {
    await wire("POST", "/", { ...CW("PutMetricData"), body: { Namespace: "LiveTest", MetricData: [{ MetricName: uniq, Value: 1 }] } });
    return uniq;
  },
};
