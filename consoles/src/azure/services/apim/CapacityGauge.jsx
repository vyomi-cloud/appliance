/* APIM Overview > Capacity: the gauge reads the NATIVE Azure Monitor `Capacity` metric of the service
 * (…/providers/Microsoft.Insights/metrics?metricnames=Capacity — the same call the SDK/CLI and
 * Monitor > Metrics make). The value is a LOAD ESTIMATE derived from the gateway requests Vyomi
 * actually served per minute against a nominal per-SKU throughput — it is NOT measured CPU. */
import { useEffect, useState } from "react";
import { Button } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { getMetrics } from "../monitor/api.js";
import { ErrorBar, InfoBar, Loading } from "../../kit/common.jsx";

const WINDOW_MIN = 30;
const color = (v) => (v >= 80 ? "#d13438" : v >= 50 ? "#ff8c00" : "#107c10");

function Gauge({ value }) {
  const r = 80, cx = 100, cy = 100, circ = Math.PI * r;
  const frac = Math.max(0, Math.min(100, value)) / 100;
  const arc = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;
  return (
    <svg width={220} height={130} role="img" aria-label={`Capacity ${value.toFixed(1)} percent (estimate)`} data-testid="apim-capacity-gauge">
      <path d={arc} fill="none" stroke="var(--colorNeutralStroke2, #e0e0e0)" strokeWidth={16} />
      <path d={arc} fill="none" stroke={color(value)} strokeWidth={16} strokeDasharray={`${circ * frac} ${circ}`} />
      <text x={cx} y={cy - 12} textAnchor="middle" fontSize={28} fontWeight={600} data-testid="apim-capacity-value">{value.toFixed(1)}%</text>
      <text x={cx - r} y={cy + 16} textAnchor="middle" fontSize={11} fill="#666">0</text>
      <text x={cx + r} y={cy + 16} textAnchor="middle" fontSize={11} fill="#666">100</text>
    </svg>
  );
}

export default function CapacityGauge({ id }) {
  const [tick, setTick] = useState(0);
  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), 5000); return () => clearInterval(t); }, []);
  const q = useAsync(() => {
    const end = new Date(Date.now() + 60000), start = new Date(Date.now() - WINDOW_MIN * 60000);
    const iso = (d) => d.toISOString().replace(/\.\d+Z$/, "Z");
    return getMetrics(id, { metricnames: "Capacity", aggregation: "Average", interval: "PT1M", timespan: `${iso(start)}/${iso(end)}` });
  }, [id, tick]);
  const m = q.data?.value?.[0];
  const pts = (m?.timeseries?.[0]?.data || []).map((p) => p.average ?? 0);
  // the newest minute is still filling, so the gauge shows the peak of the last two minutes
  const now = pts.length ? Math.max(...pts.slice(-2)) : 0;
  const peak = pts.length ? Math.max(...pts) : 0;
  return (
    <div style={{ marginTop: 12 }} data-testid="apim-capacity">
      <ErrorBar error={q.error} title="Capacity metric query failed" />
      {!m && q.loading ? <Loading /> : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 32, flexWrap: "wrap" }}>
            <Gauge value={now} />
            <div style={{ fontSize: 13 }}>
              <div>Current (peak of last 2 min): <b>{now.toFixed(1)}%</b></div>
              <div>Peak, last {WINDOW_MIN} min: <b data-testid="apim-capacity-peak">{peak.toFixed(1)}%</b></div>
              <div style={{ marginTop: 8 }}><Button size="small" icon={<ArrowClockwise20Regular />} onClick={() => setTick((n) => n + 1)}>Refresh</Button></div>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <InfoBar title="Estimated load, not measured CPU">
              This gauge is a load estimate derived from Vyomi gateway request counters: gateway requests served per minute divided by a
              nominal per-unit throughput for this service's tier and scale units. It does not measure CPU or memory, and no traffic reads 0%.
              {m?.displayDescription ? ` ${m.displayDescription.split("Basis:")[1] ? "Basis:" + m.displayDescription.split("Basis:")[1] : ""}` : ""}
            </InfoBar>
          </div>
        </>
      )}
    </div>
  );
}
