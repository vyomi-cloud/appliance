/* Shared bits for the CloudWatch service only (not the cross-service kit). */
import Box from "@cloudscape-design/components/box";
import StatusIndicator from "@cloudscape-design/components/status-indicator";

/** Minimal i18nStrings for <Wizard> (Cloudscape requires every string explicitly). */
export const WIZARD_I18N = {
  stepNumberLabel: (n) => `Step ${n}`,
  collapsedStepsLabel: (n, total) => `Step ${n} of ${total}`,
  navigationAriaLabel: "Steps",
  cancelButton: "Cancel",
  previousButton: "Previous",
  nextButton: "Next",
  submitButton: "Submit",
  optional: "optional",
};

const STATE_TYPE = { OK: "success", ALARM: "error", INSUFFICIENT_DATA: "pending" };
const STATE_TEXT = { OK: "OK", ALARM: "In alarm", INSUFFICIENT_DATA: "Insufficient data" };

export function AlarmStateBadge({ state }) {
  return <StatusIndicator type={STATE_TYPE[state] || "pending"}>{STATE_TEXT[state] || state}</StatusIndicator>;
}

/** GetMetricData's parallel Timestamps/Values arrays -> [{t, v}], oldest first. */
export function toSeries(result) {
  const ts = result?.Timestamps || [];
  const vs = result?.Values || [];
  return ts.map((t, i) => ({ t: Number(t), v: Number(vs[i]) })).sort((a, b) => a.t - b.t);
}

/** A minimal inline SVG line chart — no charting dependency; whatever datapoints came
 * back over the wire are what gets drawn, so an empty series renders as empty, not fake. */
export function LineChart({ series, height = 160, color = "#0972d3" }) {
  const pts = series || [];
  if (!pts.length) return <Box textAlign="center" color="text-body-secondary" padding="l">No data points for this time range.</Box>;
  const width = 600;
  const xs = pts.map((p) => p.t), ys = pts.map((p) => p.v);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(0, ...ys), maxY = Math.max(...ys, minY + 1);
  const x = (v) => ((v - minX) / (maxX - minX || 1)) * (width - 20) + 10;
  const y = (v) => height - 10 - ((v - minY) / (maxY - minY || 1)) * (height - 20);
  const path = pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Metric graph" preserveAspectRatio="none">
      <line x1="10" y1={height - 10} x2={width - 10} y2={height - 10} stroke="#d5dbdb" strokeWidth="1" />
      {pts.length > 1 ? <path d={path} stroke={color} strokeWidth="2" fill="none" /> : <circle cx={x(pts[0].t)} cy={y(pts[0].v)} r="3" fill={color} />}
    </svg>
  );
}

export const PERIOD_OPTIONS = [
  { label: "1 minute", value: "60" }, { label: "5 minutes", value: "300" }, { label: "15 minutes", value: "900" },
  { label: "1 hour", value: "3600" }, { label: "6 hours", value: "21600" }, { label: "1 day", value: "86400" },
];

export const fmtPeriod = (s) => (PERIOD_OPTIONS.find((p) => Number(p.value) === Number(s))?.label || `${s} seconds`);

const OP_SYMBOL = {
  GreaterThanOrEqualToThreshold: ">=", GreaterThanThreshold: ">", LessThanThreshold: "<", LessThanOrEqualToThreshold: "<=",
  LessThanLowerOrGreaterThanUpperThreshold: "outside band", LessThanLowerThreshold: "< lower band", GreaterThanUpperThreshold: "> upper band",
};

/** Human-readable alarm condition, mirroring core/cloudwatch_core.py's console row. */
export function conditionText(a) {
  if (a.AlarmRule) return a.AlarmRule;
  if (a.Metrics?.length) {
    const expr = a.Metrics.find((m) => m.ReturnData !== false)?.Expression || a.Metrics[0]?.MetricStat?.Metric?.MetricName || "expression";
    return `Metric math: ${expr} ${OP_SYMBOL[a.ComparisonOperator] || a.ComparisonOperator} ${a.Threshold}`;
  }
  return `${a.Statistic || a.ExtendedStatistic} ${a.MetricName} ${OP_SYMBOL[a.ComparisonOperator] || a.ComparisonOperator} ${a.Threshold} for ${a.DatapointsToAlarm ?? a.EvaluationPeriods} datapoints within ${Math.round((a.EvaluationPeriods * (a.Period || 60)) / 60)} minutes`;
}

export function actionsText(a) {
  const n = (a.OKActions?.length || 0) + (a.AlarmActions?.length || 0) + (a.InsufficientDataActions?.length || 0);
  return `${a.ActionsEnabled ? "Enabled" : "Disabled"} (${n} configured)`;
}

export const RETENTION_OPTIONS = [
  ["Never expire", 0], ["1 day", 1], ["3 days", 3], ["5 days", 5], ["1 week", 7], ["2 weeks", 14], ["1 month", 30],
  ["2 months", 60], ["3 months", 90], ["4 months", 120], ["5 months", 150], ["6 months", 180], ["1 year", 365],
  ["13 months", 400], ["18 months", 545], ["2 years", 731], ["3 years", 1096], ["5 years", 1827], ["6 years", 2192],
  ["7 years", 2557], ["8 years", 2922], ["9 years", 3288], ["10 years", 3653],
].map(([label, value]) => ({ label, value: String(value) }));
