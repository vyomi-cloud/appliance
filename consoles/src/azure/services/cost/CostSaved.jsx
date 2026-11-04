/* Billing > Invoices: the "cost saved" dashboard (what the same inventory would cost on real Azure, accrued from each
 * resource's creation) plus the simulated monthly invoices. Backed by core/azure_billing_ext_core.py. Payment methods
 * are never collected. */
import { Link } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { arm, armList, money, subPath } from "../../kit/az08.js";
import { downloadCsv, ErrorBar, InfoBar, Loading } from "../../kit/common.jsx";
import CostShell from "./CostShell.jsx";

const Tile = ({ label, value, hint, accent }) => (
  <div style={{ border: "1px solid var(--colorNeutralStroke2)", borderRadius: 8, padding: "14px 16px", minWidth: 190, background: accent ? "var(--colorBrandBackground2)" : undefined }}>
    <div style={{ fontSize: 12, color: "var(--colorNeutralForeground3)" }}>{label}</div>
    <div style={{ fontSize: 28, fontWeight: 600, lineHeight: 1.25 }} data-testid={`tile-${label}`}>{value}</div>
    {hint && <div style={{ fontSize: 12, color: "var(--colorNeutralForeground3)" }}>{hint}</div>}
  </div>
);

function Bars({ rows, valueKey, labelKey, ariaLabel }) {
  const max = Math.max(1, ...rows.map((r) => r[valueKey]));
  return (
    <div role="img" aria-label={ariaLabel} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((r) => (
        <div key={r[labelKey]} style={{ display: "grid", gridTemplateColumns: "150px 1fr 90px", gap: 8, alignItems: "center", fontSize: 13 }}>
          <span>{r[labelKey]}</span>
          <div style={{ background: "var(--colorNeutralBackground4)", borderRadius: 3, height: 12 }}>
            <div style={{ width: `${(100 * r[valueKey]) / max}%`, background: "var(--colorBrandBackground)", height: 12, borderRadius: 3 }} />
          </div>
          <span style={{ textAlign: "right" }}>{money(r[valueKey])}</span>
        </div>
      ))}
    </div>
  );
}

export function Invoices() {
  const saved = useAsync(() => arm("GET", `${subPath()}/providers/Microsoft.Billing/costSaved`, undefined, {}, "2024-01-01"), []);
  const inv = useAsync(() => armList(`${subPath()}/providers/Microsoft.Billing/invoices`, { "api-version": "2024-01-01" }), []);
  const s = saved.data;
  return (
    <CostShell active="invoices">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.invoices" title="Invoices and cost saved">
          <InfoBar>These invoices are simulated and marked as such: nothing is ever billed. The dollar figures are what real Azure would have charged for the resources Vyomi runs for you, which is the money you keep.</InfoBar>
          <ErrorBar error={saved.error || inv.error} />
          {saved.loading ? <Loading /> : s && (
            <>
              <h3 style={{ marginTop: 16 }}>Cost saved with Vyomi</h3>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                <Tile accent label="Saved so far" value={money(s.totalSaved)} hint={`across ${s.resourceCount} resource(s)`} />
                <Tile label="Saved this month" value={money(s.thisMonthSaved)} />
                <Tile label="Run rate" value={`${money(s.monthlyRunRate)}/mo`} hint={`${money(s.annualizedSavings)} a year`} />
                <Tile label="Actually billed" value={money(s.actualSpend)} hint="Vyomi runs on your machine" />
              </div>
              {s.monthly.length > 0 && <section className="vy-section"><h4>By month</h4><Bars rows={s.monthly} valueKey="saved" labelKey="month" ariaLabel="Cost saved by month" /></section>}
              {s.byService.length > 0 && <section className="vy-section"><h4>By service</h4><Bars rows={s.byService} valueKey="saved" labelKey="service" ariaLabel="Cost saved by service" /></section>}
              {s.topResources.length > 0 && (
                <section className="vy-section"><h4>Top resources</h4>
                  <table className="vy-grid"><thead><tr><th>Resource</th><th>Service</th><th>Resource group</th><th>List price / month</th><th>Since</th><th>Saved</th></tr></thead>
                    <tbody>{s.topResources.map((r) => <tr key={`${r.type}/${r.name}`}><td>{r.name}</td><td>{r.service}</td><td>{r.resourceGroup}</td><td>{money(r.monthlyListPrice)}</td><td>{r.since}</td><td>{money(r.saved)}</td></tr>)}</tbody></table>
                </section>
              )}
              {!s.resourceCount && <p className="vy-muted">Create resources and this dashboard fills in. <Link href="#/">Create a resource</Link></p>}
              <p className="vy-muted" style={{ fontSize: 12 }}>{s.note}</p>
            </>
          )}
          <h3 style={{ marginTop: 20 }}>Simulated invoices</h3>
          {inv.loading ? <Loading /> : (
            <>
              <button type="button" className="vy-link" style={{ background: "none", border: 0, padding: 0, cursor: "pointer", color: "var(--colorBrandForeground1)" }}
                onClick={() => downloadCsv("invoices.csv", [{ key: "n", label: "Invoice", value: (r) => r.name }, { key: "p", label: "Period", value: (r) => r.properties.invoicePeriodStartDate }, { key: "s", label: "Status", value: (r) => r.properties.status }, { key: "d", label: "Amount due", value: (r) => r.properties.amountDue.value }, { key: "a", label: "Avoided", value: (r) => r.properties.avoidedAmount.value }], inv.data || [])}>Export to CSV</button>
              <table className="vy-grid" aria-label="Invoices">
                <thead><tr><th>Invoice</th><th>Billing period</th><th>Status</th><th>Amount due</th><th>Charges avoided</th></tr></thead>
                <tbody>{(inv.data || []).length ? inv.data.map((r) => (
                  <tr key={r.name}><td>{r.name}</td><td>{r.properties.invoicePeriodStartDate} to {r.properties.invoicePeriodEndDate}</td><td>{r.properties.status} (simulated)</td>
                    <td>{money(r.properties.amountDue.value)}</td><td>{money(r.properties.avoidedAmount.value)}</td></tr>
                )) : <tr><td colSpan={5} className="vy-muted">No invoices yet: they appear once Vyomi runs billable resources.</td></tr>}</tbody>
              </table>
            </>
          )}
        </CapabilityContainer>
      </div>
    </CostShell>
  );
}
