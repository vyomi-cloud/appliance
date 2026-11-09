/* Cosmos DB "Power BI" panel: Dev Simplified. Power BI is a Microsoft SaaS product Vyomi does not run, so this page makes
 * no connector claim. It gives what a Power BI Desktop user would paste (endpoint + read-only key) and a CSV / JSON export of the
 * account's container inventory generated from the real databases and containers. */
import { useState } from "react";
import { Button } from "@fluentui/react-components";
import { ArrowDownload20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { downloadCsv, ErrorBar, InfoBar, KV, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

function saveJson(name, obj) {
  const el = document.createElement("a");
  el.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" }));
  el.download = name;
  document.body.appendChild(el); el.click(); el.remove();
  setTimeout(() => URL.revokeObjectURL(el.href), 1000);
}

export default function PowerBi({ a }) {
  const [show, setShow] = useState(false);
  const inv = useAsync(() => api.listAllContainers(a.resourceGroup, a.name), [a.id]);
  const cs = useAsync(() => api.listConnectionStrings(a.resourceGroup, a.name), [a.id]);
  const endpoint = api.accountEndpoint(a.name);
  const ro = (cs.data?.connectionStrings || []).find((c) => /read-only/i.test(c.description || "")) || (cs.data?.connectionStrings || [])[0];
  const rows = (inv.data || []).map((c) => ({
    account: a.name, database: c.database, container: c.id,
    partitionKey: (c.partitionKey?.paths || []).join(","), throughput: c.throughput, defaultTtl: c.defaultTtl ?? "",
  }));
  const COLS = [{ key: "account", label: "account" }, { key: "database", label: "database" }, { key: "container", label: "container" },
    { key: "partitionKey", label: "partitionKey" }, { key: "throughput", label: "throughput" }, { key: "defaultTtl", label: "defaultTtl" }];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Power BI</div>
      <CapabilityContainer id="azure.cosmos.powerbi" title="Power BI">
        <p>Open Power BI Desktop, choose Get data, then Azure Cosmos DB (v1) and paste the account endpoint. Use the read-only key when asked for the account key.</p>
        <ErrorBar error={inv.error || cs.error} />
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "12px 0" }}>
          <KV label="Account endpoint" value={endpoint} />
          <KV label="Read-only connection string" value={cs.loading ? "Loading..." : ro ? (show ? ro.connectionString : "••••••••••••") : "--"} />
        </div>
        <div className="vy-cmdbar" role="toolbar" aria-label="Power BI commands">
          <Button onClick={() => setShow((s) => !s)} disabled={!ro}>{show ? "Hide connection string" : "Show connection string"}</Button>
          <Button icon={<ArrowDownload20Regular />} disabled={!rows.length} onClick={() => downloadCsv(`${a.name}-containers.csv`, COLS, rows)}>Download containers (CSV)</Button>
          <Button icon={<ArrowDownload20Regular />} disabled={!rows.length} onClick={() => saveJson(`${a.name}-containers.json`, { endpoint, containers: rows })}>Download containers (JSON)</Button>
        </div>
        {inv.loading && !inv.data ? <Loading /> : (
          <table className="vy-grid" style={{ width: "100%" }} aria-label="Containers">
            <thead><tr>{COLS.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={COLS.length}>This account has no containers yet.</td></tr>}
              {rows.map((r) => <tr key={`${r.database}/${r.container}`}>{COLS.map((c) => <td key={c.key}>{String(r[c.key] ?? "")}</td>)}</tr>)}
            </tbody>
          </table>
        )}
        <InfoBar>Dev Simplified: Vyomi does not run Power BI and offers no Power BI connector or one-click publish. The details above and the CSV / JSON exports are generated from this account's real databases and containers so you can load them into Power BI Desktop yourself.</InfoBar>
      </CapabilityContainer>
    </>
  );
}
