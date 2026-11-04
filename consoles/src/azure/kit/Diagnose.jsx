/* "Diagnose and solve problems" shared by AKS / API Management / App Configuration / Cognitive Services / App Service.
 * Every detector is computed server-side from the resource's LIVE record, its child resources and its own Activity log
 * (core/azure_diagnose_core.py, GET {id}/providers/Microsoft.Vyomi/diagnostics) -- never canned text. */
import { useState } from "react";
import { Button, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, Loading, fmtDate } from "./common.jsx";

const COLOR = { Critical: "#d13438", Warning: "#ca5010", Info: "#0078d4", Healthy: "#107c10" };
const ICON = { Critical: "✗", Warning: "!", Info: "i", Healthy: "✓" };

export default function Diagnose({ id, name, title }) {
  const { data, loading, error, reload } = useAsync(() => restJson("GET", `${id}/providers/Microsoft.Vyomi/diagnostics`, { query: { "api-version": "2024-01-01" } }), [id]);
  const [cat, setCat] = useState("All");
  const dets = data?.detectors || [];
  const cats = ["All", ...Array.from(new Set(dets.map((d) => d.category)))];
  const rows = dets.filter((d) => cat === "All" || d.category === cat);
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Diagnose and solve problems`}</div>
      <CapabilityContainer id="azure.common.diagnose" title="Diagnose and solve problems"
        actions={<Button size="small" icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</Button>}>
        <ErrorBar error={error} title="Failed to run diagnostics" />
        {loading && !data ? <Loading label="Running detectors..." /> : data && (
          <>
            <p style={{ fontSize: 13 }} data-testid="diagnose-summary">
              <b style={{ color: COLOR[data.overall] }}>{data.overall === "Healthy" ? "No problems detected" : `${data.overall} findings detected`}</b>
              {" — "}{data.counts.Critical} critical, {data.counts.Warning} warning, {data.counts.Info} informational, {data.counts.Healthy} healthy. Checked {fmtDate(data.generatedAt)} from this resource's live configuration and recorded operations.
            </p>
            <TabList size="small" selectedValue={cat} onTabSelect={(_, d) => setCat(d.value)} style={{ marginBottom: 8 }}>
              {cats.map((c) => <Tab key={c} value={c}>{c}</Tab>)}
            </TabList>
            <Table size="small" aria-label="Detectors" className="vy-grid">
              <TableHeader><TableRow>
                <TableHeaderCell style={{ width: 90 }}>Status</TableHeaderCell><TableHeaderCell style={{ width: 220 }}>Detector</TableHeaderCell>
                <TableHeaderCell>Finding</TableHeaderCell><TableHeaderCell>Recommended action</TableHeaderCell>
              </TableRow></TableHeader>
              <TableBody>
                {rows.map((d) => (
                  <TableRow key={d.id} data-detector={d.id} data-status={d.status}>
                    <TableCell><span style={{ color: COLOR[d.status], fontWeight: 600 }}>{ICON[d.status]} {d.status}</span></TableCell>
                    <TableCell>{d.name}<div className="vy-muted" style={{ fontSize: 11 }}>{d.category}</div></TableCell>
                    <TableCell style={{ whiteSpace: "normal" }}>{d.detail}</TableCell>
                    <TableCell style={{ whiteSpace: "normal" }}>{d.recommendation || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CapabilityContainer>
    </>
  );
}
