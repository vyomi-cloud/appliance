/* Resource group Insights (preview): GET {rg}/providers/Microsoft.Vyomi/insights (core/azure_rgtools_core.py), computed from the group's real
 * resources, tags, VM power states, locks, alert rules, resource health, Advisor and Activity log. No metrics or cost are invented. */
import { Button } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const Tile = ({ label, value, tone }) => (
  <div style={{ border: "1px solid var(--colorNeutralStroke2, #e0e0e0)", borderRadius: 4, padding: "10px 14px", minWidth: 130 }}>
    <div className="vy-muted" style={{ fontSize: 12 }}>{label}</div>
    <div style={{ fontSize: 24, fontWeight: 600, color: tone === "bad" ? "#d13438" : tone === "warn" ? "#ca5010" : undefined }}>{value}</div>
  </div>
);

const Mini = ({ title, rows, cols, empty }) => (
  <section className="vy-section" style={{ flex: "1 1 320px" }}>
    <b>{title}</b>
    <table className="vy-grid" style={{ marginTop: 6 }}>
      <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{rows.length ? rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v}</td>)}</tr>) : <tr><td colSpan={cols.length} className="vy-muted">{empty}</td></tr>}</tbody>
    </table>
  </section>
);

export default function Insights({ name }) {
  const { data: d, loading, error, reload } = useAsync(() => api.getInsights(name), [name]);
  const entries = (o) => Object.entries(o || {});
  return (
    <CapabilityContainer id="azure.resourcegroups.tools" title={`${name} | Insights (preview)`}
      actions={<Button size="small" icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</Button>}>
      <ErrorBar error={error} title="Failed to load Insights" />
      {loading && !d ? <Loading /> : d && (
        <>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "8px 0 16px" }}>
            <Tile label="Resources" value={d.inventory.resourceCount} />
            <Tile label="Tag coverage" value={`${d.tags.coveragePercent}%`} tone={d.tags.untagged ? "warn" : undefined} />
            <Tile label="Virtual machines" value={d.compute.virtualMachines} />
            <Tile label="Failed provisioning" value={d.provisioning.failed.length} tone={d.provisioning.failed.length ? "bad" : undefined} />
            <Tile label="Alert rules" value={d.alertRules} />
            <Tile label="Locks" value={d.locks} />
            <Tile label="Operations (24h)" value={d.activity.last24h} />
            <Tile label="Failed (24h)" value={d.activity.failed} tone={d.activity.failed ? "bad" : undefined} />
          </div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <Mini title="Resources by type" cols={["Type", "Count"]} rows={d.inventory.byType.map((t) => [t.type, t.count])} empty="No resources" />
            <Mini title="Resources by location" cols={["Location", "Count"]} rows={d.inventory.byLocation.map((t) => [t.location, t.count])} empty="No resources" />
            <Mini title="Untagged resources" cols={["Resource"]} rows={d.tags.untaggedResources.map((i) => [i.split("/").slice(-3).join("/")])} empty="Every resource carries at least one tag" />
            <Mini title="Tag keys in use" cols={["Key", "Resources"]} rows={d.tags.keys.map((k) => [k.key, k.count])} empty="No tags" />
            <Mini title="Virtual machine power state" cols={["State", "VMs"]} rows={entries(d.compute.powerStates)} empty="No virtual machines" />
            {d.health && <Mini title="Resource health" cols={["Availability", "Resources"]} rows={entries(d.health.statuses)} empty="No resources" />}
            {d.advisor && <Mini title="Advisor recommendations" cols={["Impact", "Count"]} rows={entries(d.advisor.byImpact)} empty="No recommendations" />}
            <Mini title="Top operations (24h)" cols={["Operation", "Count"]} rows={d.activity.topOperations.map((o) => [o.operation, o.count])} empty="No recorded operations" />
          </div>
        </>
      )}
    </CapabilityContainer>
  );
}
