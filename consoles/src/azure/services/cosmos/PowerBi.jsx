/* Cosmos DB "Power BI" panel. Vyomi serves REAL export endpoints over the account's container data (core/azure_cosmos_core.py:
 * an OData v4 feed that Power BI Desktop's "OData feed" source can read, plus CSV / JSON / Parquet files). The Power BI service
 * itself is not in scope and no connector is claimed. */
import { Link } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { WIRE_BASE } from "../../../common/wire.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const abs = (path) => new URL(WIRE_BASE + path, location.href).toString();

export default function PowerBi({ a }) {
  const inv = useAsync(() => api.listAllContainers(a.resourceGroup, a.name), [a.id]);
  const rows = inv.data || [];
  const dbs = [...new Set(rows.map((c) => c.database))];
  const enc = encodeURIComponent;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Power BI</div>
      <CapabilityContainer id="azure.cosmos.powerbi" title="Power BI">
        <p>In Power BI Desktop choose Get data, then OData feed, and paste one of the feed URLs below (one feed per database; each container is an entity set). Or download a container as a file.</p>
        <ErrorBar error={inv.error} />
        {inv.loading && !inv.data ? <Loading /> : (
          <>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "12px 0" }}>
              {dbs.length === 0 && <KV label="OData feed" value="Create a database and container first." />}
              {dbs.map((d) => <KV key={d} label={`OData feed: ${d}`} value={<code data-testid="odata-url">{abs(`/vyomi/odata/${enc(d)}`)}</code>} />)}
            </div>
            <table className="vy-grid" style={{ width: "100%" }} aria-label="Containers">
              <thead><tr><th>Database</th><th>Container</th><th>Partition key</th><th>Download</th></tr></thead>
              <tbody>
                {rows.length === 0 && <tr><td colSpan={4}>This account has no containers yet.</td></tr>}
                {rows.map((r) => (
                  <tr key={`${r.database}/${r.id}`}>
                    <td>{r.database}</td><td>{r.id}</td><td>{(r.partitionKey?.paths || []).join(",")}</td>
                    <td>{["csv", "json", "parquet"].map((f) => (
                      <span key={f}><Link href={abs(`/vyomi/export/${enc(r.database)}/${enc(r.id)}.${f}`)} download={`${r.id}.${f}`}>{f.toUpperCase()}</Link>{" "}</span>
                    ))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <InfoBar>These are real exports of the data in your containers. Parquet files need the offline appliance (Nano offers OData, CSV and JSON). The Power BI service itself is not in scope for Vyomi, so there is no connector, publish or workspace; load the feed or files in Power BI Desktop yourself.</InfoBar>
      </CapabilityContainer>
    </>
  );
}
