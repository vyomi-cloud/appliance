/* SMS delivery statistics, read from the real AWS/SNS CloudWatch metrics (native CloudWatch wire)
 * that SNS publishes for every SMS this environment accepts. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { awsJson, asList } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { LineChart } from "../cloudwatch/common.jsx";

const CW = (op, payload) => awsJson("monitoring", `GraniteServiceVersion20100801.${op}`, payload);
const HOURS = 24;

async function points(metricName, dims, statistic, period) {
  const end = new Date(), start = new Date(end - HOURS * 3600_000);
  const r = await CW("GetMetricStatistics", { Namespace: "AWS/SNS", MetricName: metricName, Dimensions: dims,
    StartTime: start.toISOString(), EndTime: new Date(+end + 60_000).toISOString(), Period: period, Statistics: [statistic] });
  return (r.Datapoints || []).map((p) => ({ t: new Date(p.Timestamp).getTime(), v: Number(p[statistic]) })).sort((a, b) => a.t - b.t);
}
const total = (pts) => pts.reduce((a, p) => a + p.v, 0);

export function DeliveryStatistics() {
  const s = useAsync(async () => ({
    delivered: await points("NumberOfNotificationsDelivered", [], "Sum", 300),
    rate: await points("SMSSuccessRate", [], "Average", 300),
    spend: await points("SMSMonthToDateSpentUSD", [], "Maximum", 300),
  }), []);
  const d = s.data;
  return (
    <CapabilityContainer id="sns.sms.delivery-statistics" title="Delivery statistics (UTC)" description={`Text messages accepted by this environment in the last ${HOURS} hours.`}
      actions={<Button iconName="refresh" onClick={s.reload}>Refresh</Button>}>
      {s.loading ? <StatusIndicator type="loading">Loading</StatusIndicator> : s.error ? <ErrorAlert error={s.error} /> : (
        <SpaceBetween size="m">
          <KeyValue columns={3} items={[
            ["Notifications delivered", <span data-testid="sms-delivered">{total(d.delivered)}</span>],
            ["Delivery success rate", d.rate.length ? `${Math.round((total(d.rate) / d.rate.length) * 100)}%` : "-"],
            ["Month-to-date spend (USD)", d.spend.length ? d.spend[d.spend.length - 1].v.toFixed(5) : "0"],
          ]} />
          <Box variant="h3">Notifications delivered</Box>
          <LineChart series={d.delivered} />
        </SpaceBetween>
      )}
    </CapabilityContainer>
  );
}

export function DeliveryByCountry() {
  const s = useAsync(async () => {
    const ms = asList((await CW("ListMetrics", { Namespace: "AWS/SNS", MetricName: "NumberOfNotificationsDelivered" })).Metrics);
    const countries = [...new Set(ms.flatMap((m) => asList(m.Dimensions).filter((x) => x.Name === "Country").map((x) => x.Value)))].sort();
    const rows = [];
    for (const c of countries) {
      const dims = [{ Name: "Country", Value: c }];
      const delivered = total(await points("NumberOfNotificationsDelivered", dims, "Sum", 300));
      const rate = await points("SMSSuccessRate", dims, "Average", 300);
      rows.push({ country: c, delivered, rate: rate.length ? Math.round((total(rate) / rate.length) * 100) : null });
    }
    return rows;
  }, []);
  return (
    <CapabilityContainer id="sns.sms.delivery-statistics" title="Delivery statistics by country" description={`Last ${HOURS} hours.`}
      actions={<Button iconName="refresh" onClick={s.reload}>Refresh</Button>}>
      {s.loading ? <StatusIndicator type="loading">Loading</StatusIndicator> : s.error ? <ErrorAlert error={s.error} /> : (
        <Table variant="embedded" items={s.data} trackBy="country"
          columnDefinitions={[
            { id: "c", header: "Country", cell: (r) => r.country },
            { id: "d", header: "Notifications delivered", cell: (r) => r.delivered },
            { id: "r", header: "Success rate", cell: (r) => (r.rate == null ? "-" : `${r.rate}%`) },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No text messages sent yet</b></Box>} />
      )}
    </CapabilityContainer>
  );
}
