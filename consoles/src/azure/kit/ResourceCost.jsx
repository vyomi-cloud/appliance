/* Per-resource "Cost Management" tab: month-to-date real-cloud cost and the money saved by running it on Vyomi, from the
 * same engines as Cost Management (core/azure_cost_core.py + core/azure_billing_ext_core.py). */
import { Link } from "@fluentui/react-components";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { CapabilityContainer } from "./Capability.jsx";
import { arm, money, subPath } from "./az08.js";
import { ErrorBar, KV, Loading } from "./common.jsx";

export default function ResourceCost({ resource, capId, title }) {
  const q = useAsync(() => restJson("POST", `${subPath()}/providers/Microsoft.CostManagement/query`, {
    query: { "api-version": "2023-11-01" }, body: { type: "ActualCost", timeframe: "MonthToDate", dataset: { grouping: [{ type: "Dimension", name: "ResourceId" }] } } }), []);
  const saved = useAsync(() => arm("GET", `${subPath()}/providers/Microsoft.Billing/costSaved`, undefined, {}, "2024-01-01"), []);
  const mtd = (q.data?.properties?.rows || []).find((r) => String(r[1]).toLowerCase() === resource.toLowerCase());
  const mine = (saved.data?.topResources || []).find((r) => r.name === resource);
  return (
    <CapabilityContainer id={capId} title={title}>
      <ErrorBar error={q.error || saved.error} />
      {q.loading || saved.loading ? <Loading /> : (
        <section className="vy-section" style={{ maxWidth: 560 }}>
          <KV label="Real-Azure cost, month to date" value={mtd ? money(mtd[0]) : "--"} />
          <KV label="List price per month" value={mine ? money(mine.monthlyListPrice) : "--"} />
          <KV label="Saved with Vyomi since creation" value={mine ? money(mine.saved) : "--"} />
          <KV label="Billed to you" value={money(0)} />
          <p style={{ fontSize: 13 }}>See <Link href="#/cost/analysis">Cost analysis</Link> for every resource and <Link href="#/cost/invoices">Invoices</Link> for the full cost-saved dashboard.</p>
        </section>
      )}
    </CapabilityContainer>
  );
}
