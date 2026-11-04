/* Cosmos DB Scale / throughput consumption: request units consumed per minute, from the TotalRequestUnits metric
 * (core/observability_core.azure_series). RU charges are MODELLED from each measured request's size using Microsoft's
 * published cost model (1 KB point read = 1 RU, 1 KB write ~ 5 RU); provisioned throughput is not enforced (no 429s). */
import { ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import { getMetrics } from "../monitor/api.js";

export default function CosmosScale({ a }) {
  const iso = (d) => d.toISOString().slice(0, 19) + "Z";
  const q = useAsync(() => {
    const end = new Date(Date.now() + 60000), start = new Date(end.getTime() - 3600000);
    return getMetrics(a.id, { metricnames: "TotalRequestUnits,TotalRequests", aggregation: "Total", interval: "PT1M", timespan: `${iso(start)}/${iso(end)}` });
  }, [a.id]);
  const series = (n) => (q.data?.value || []).find((v) => v.name.value === n)?.timeseries?.[0]?.data || [];
  const ru = series("TotalRequestUnits").map((p) => ({ t: p.timeStamp, v: p.total })), reqs = series("TotalRequests").reduce((s, p) => s + p.total, 0);
  const totalRu = ru.reduce((s, p) => s + p.v, 0), peak = ru.length ? Math.max(...ru.map((p) => p.v)) / 60 : 0;
  const w = 640, h = 150, max = Math.max(1, ...ru.map((p) => p.v)), bw = ru.length ? Math.min(30, (w - 40) / ru.length) : 0;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Scale</div>
      <CapabilityContainer id="azure.cosmos.scale_ru" title="Throughput consumption" actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={q.reload}>Refresh</ToolbarButton>}>
        <ErrorBar error={q.error} />
        {q.loading && !q.data ? <Loading /> : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12, margin: "8px 0" }}>
              <div className="vy-section"><h3>Requests (last hour)</h3><div style={{ fontSize: 24, fontWeight: 600 }} data-testid="scale-requests">{reqs}</div></div>
              <div className="vy-section"><h3>RUs consumed</h3><div style={{ fontSize: 24, fontWeight: 600 }} data-testid="scale-ru">{Math.round(totalRu * 100) / 100}</div></div>
              <div className="vy-section"><h3>Peak RU/s</h3><div style={{ fontSize: 24, fontWeight: 600 }}>{Math.round(peak * 100) / 100}</div></div>
            </div>
            <svg width={w} height={h} role="img" aria-label="RU consumed per minute" style={{ maxWidth: "100%" }}>
              <line x1={30} y1={h - 20} x2={w - 4} y2={h - 20} stroke="#ccc" /><text x={2} y={12} fontSize="10" fill="#666">{max}</text>
              {ru.map((p, i) => <rect key={p.t} x={34 + i * bw} y={h - 20 - (p.v / max) * (h - 36)} width={Math.max(2, bw - 3)} height={(p.v / max) * (h - 36)} fill="#0078d4"><title>{p.t}: {p.v} RU</title></rect>)}
            </svg>
            {!ru.length && <p className="vy-muted" data-testid="scale-empty">No requests against this account in the last hour - nothing to chart.</p>}
            <p style={{ fontSize: 12 }}>RU charges are modelled from each measured request's size using the published Cosmos DB cost model. Provisioned throughput (manual / autoscale) is not enforced, so requests are never rate-limited (429).</p>
          </>
        )}
      </CapabilityContainer>
    </>
  );
}
