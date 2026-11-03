/* Advisor recommendations shared by every Azure blade (panel + Overview "Recommendations" tab):
 * real Microsoft.Advisor/recommendations from core/azure_health_core.py's rule set, evaluated
 * over each resource's stored configuration, with real Postpone (snooze) / Dismiss suppressions. */
import { Button, Select } from "@fluentui/react-components";
import { useState } from "react";
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { useNotify } from "../../common/notify.jsx";
import { getSubscription } from "./arm.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, Loading } from "./common.jsx";

const API = "2023-01-01";
const base = () => `/subscriptions/${getSubscription()}/providers/Microsoft.Advisor/recommendations`;

/** scope: resource id, resource-group id, or "" for the whole subscription. */
export default function Advisor({ scope = "", name, title, bare = false }) {
  const notify = useNotify();
  const [cat, setCat] = useState("");
  const [showSupp, setShowSupp] = useState(false);
  const rg = (scope.split("/").filter(Boolean)[3]) || "";
  const { data, loading, error, reload } = useAsync(async () => {
    const f = [rg && `ResourceGroup eq '${rg}'`, cat && `Category eq '${cat}'`].filter(Boolean).join(" and ");
    const v = (await restJson("GET", base(), { query: { "api-version": API, ...(f ? { $filter: f } : {}) } })).value || [];
    const s = scope.toLowerCase();
    return s ? v.filter((r) => r.properties.resourceMetadata.resourceId.toLowerCase().startsWith(s)) : v;
  }, [scope, cat]);
  const act = async (r, ttl) => {
    try { await restJson("PUT", `${base()}/${r.name}/suppressions/${ttl === "-1" ? "dismiss" : "snooze"}`, { query: { "api-version": API }, body: { properties: { ttl } } }); notify.success(ttl === "-1" ? "Recommendation dismissed." : "Recommendation postponed for 7 days.", "Updated"); reload(); }
    catch (e) { notify.error(e, "Failed to update the recommendation"); }
  };
  const undo = async (r) => {
    for (const n of r.properties.suppressionIds) await restJson("DELETE", `${base()}/${r.name}/suppressions/${n}`, { query: { "api-version": API } });
    reload();
  };
  const rows = (data || []).filter((r) => showSupp || !r.properties.suppressionIds.length);
  const body = (
    <CapabilityContainer id="azure.common.advisor" title="Recommendations">
      <div style={{ display: "flex", gap: 8, margin: "8px 0" }}>
        <Select size="small" value={cat} onChange={(_, d) => setCat(d.value)} aria-label="Category">
          <option value="">All categories</option>{["Security", "Reliability", "Cost", "OperationalExcellence", "Performance"].map((c) => <option key={c}>{c}</option>)}
        </Select>
        <label style={{ fontSize: 13 }}><input type="checkbox" checked={showSupp} onChange={(e) => setShowSupp(e.target.checked)} /> Show postponed / dismissed</label>
        <Button size="small" onClick={reload}>Refresh</Button>
      </div>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid" aria-label="Advisor recommendations">
          <thead><tr><th>Category</th><th>Impact</th><th>Description</th><th>Impacted resource</th><th>Actions</th></tr></thead>
          <tbody>
            {rows.length ? rows.map((r) => (
              <tr key={r.id} style={r.properties.suppressionIds.length ? { opacity: 0.55 } : undefined}>
                <td>{r.properties.category}</td><td>{r.properties.impact}</td>
                <td><b>{r.properties.shortDescription.problem}</b><div style={{ fontSize: 12 }}>{r.properties.shortDescription.solution}</div></td>
                <td>{r.properties.impactedValue}</td>
                <td>{r.properties.suppressionIds.length
                  ? <Button size="small" onClick={() => undo(r)}>Reactivate</Button>
                  : <><Button size="small" onClick={() => act(r, "07:00:00:00")}>Postpone</Button> <Button size="small" onClick={() => act(r, "-1")}>Dismiss</Button></>}</td>
              </tr>
            )) : <tr><td colSpan={5} className="vy-muted">No active recommendations. Your resources follow the configuration checks Vyomi evaluates.</td></tr>}
          </tbody>
        </table>
      )}
    </CapabilityContainer>
  );
  return bare ? body : <><div className="vy-panel-title">{title || `${name} | Advisor recommendations`}</div>{body}</>;
}
