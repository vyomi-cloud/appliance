/* "Add Azure AI Search" for a storage account / Cosmos DB account / SQL database: pick or create a search service
 * (Microsoft.Search/searchServices), then Import data = data source + index + indexer, run it, and query the index.
 * Backed by core/azure_search_core.py. Blob data sources are really read; Cosmos / SQL data sources are stored and
 * their indexer reports the real failure (Vyomi indexers only read Blob data). */
import { useState } from "react";
import { Button, Field, Input, Select } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { CapabilityContainer } from "./Capability.jsx";
import { listResourceGroups } from "./arm.js";
import { arm, armList, rgPath, subPath } from "./az08.js";
import { ErrorBar, InfoBar, Loading } from "./common.jsx";

const svcBase = (s) => `${rgPath(s.rg)}/providers/Microsoft.Search/searchServices/${s.name}`;
const rgOf = (id) => (id.match(/resourceGroups\/([^/]+)/i) || [])[1];

/** source = {kind: "storage"|"cosmos"|"sql", capId, title, account, containers?: string[], connectionString, containerName?}. */
export default function AiSearchIntegration({ source }) {
  const notify = useNotify();
  const services = useAsync(() => armList(`${subPath()}/providers/Microsoft.Search/searchServices`), []);
  const rgs = useAsync(() => listResourceGroups(), []);
  const [sel, setSel] = useState("");
  const [nu, setNu] = useState({ name: "", rg: "", sku: "basic" });
  const [container, setContainer] = useState(source.containers?.[0] || source.containerName || "");
  const [indexName, setIndexName] = useState(`${(source.account || "data").toLowerCase().replace(/[^a-z0-9]/g, "")}-index`.slice(0, 40));
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState(null);
  const list = services.data || [];
  const current = list.find((s) => s.name === sel);

  const create = async () => {
    setBusy(true);
    try {
      await arm("PUT", `${rgPath(nu.rg)}/providers/Microsoft.Search/searchServices/${nu.name}`, { location: "eastus", sku: { name: nu.sku }, properties: { replicaCount: 1, partitionCount: 1 } }, {}, "2023-11-01");
      notify.success(`Created search service '${nu.name}'.`, "Search service created");
      setNu({ ...nu, name: "" }); await services.reload(); setSel(nu.name);
    } catch (e) { notify.error(e, "Failed to create the search service"); } finally { setBusy(false); }
  };

  const importData = async () => {
    const s = { rg: rgOf(current.id), name: current.name };
    setBusy(true); setResult(null);
    try {
      const base = svcBase(s);
      await arm("PUT", `${base}/indexes/${indexName}`, { fields: [
        { name: "id", type: "Edm.String", key: true }, { name: "content", type: "Edm.String", searchable: true },
        { name: "metadata_storage_name", type: "Edm.String", filterable: true, sortable: true } ] }, {}, "2023-11-01");
      await arm("PUT", `${base}/datasources/${indexName}-ds`, { type: source.kind === "storage" ? "azureblob" : source.kind === "cosmos" ? "cosmosdb" : "azuresql",
        credentials: { connectionString: source.connectionString }, container: { name: container || source.account } }, {}, "2023-11-01");
      await arm("PUT", `${base}/indexers/${indexName}-ixr`, { dataSourceName: `${indexName}-ds`, targetIndexName: indexName, parameters: { configuration: { parsingMode: "default" } } }, {}, "2023-11-01");
      await arm("POST", `${base}/indexers/${indexName}-ixr/run`, {}, {}, "2023-11-01");
      const st = await arm("GET", `${base}/indexers/${indexName}-ixr/status`, undefined, {}, "2023-11-01");
      setResult({ ...st.lastResult, base });
    } catch (e) { notify.error(e, "Import data failed"); } finally { setBusy(false); }
  };

  const search = async () => {
    try { setHits((await arm("POST", `${result.base}/indexes/${indexName}/docs/search`, { search: q || "*", $top: 10, $count: "true" }, {}, "2023-11-01"))); }
    catch (e) { notify.error(e, "Search failed"); }
  };

  return (
    <CapabilityContainer id={source.capId} title={source.title}>
      <ErrorBar error={services.error} />
      {services.loading ? <Loading /> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 720 }}>
          <section className="vy-section"><h3>Connect to your search service</h3>
            <Field label="Azure AI Search service">
              <Select value={sel} onChange={(_, d) => setSel(d.value)} aria-label="Azure AI Search service">
                <option value="">Select a search service</option>
                {list.map((s) => <option key={s.id} value={s.name}>{s.name} ({s.sku?.name})</option>)}
              </Select>
            </Field>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginTop: 8 }}>
              <Field label="New service name"><Input value={nu.name} onChange={(_, d) => setNu({ ...nu, name: d.value })} aria-label="New search service name" /></Field>
              <Field label="Resource group"><Select value={nu.rg} onChange={(_, d) => setNu({ ...nu, rg: d.value })} aria-label="Search service resource group">
                <option value="">Select</option>{(rgs.data || []).map((r) => <option key={r.name}>{r.name}</option>)}</Select></Field>
              <Field label="Pricing tier"><Select value={nu.sku} onChange={(_, d) => setNu({ ...nu, sku: d.value })} aria-label="Search pricing tier">
                {["free", "basic", "standard", "standard2", "standard3"].map((t) => <option key={t}>{t}</option>)}</Select></Field>
              <Button disabled={busy || !nu.name || !nu.rg} onClick={create}>Create search service</Button>
            </div>
          </section>
          {current && (
            <section className="vy-section"><h3>Import data</h3>
              {source.containers && <Field label="Container"><Select value={container} onChange={(_, d) => setContainer(d.value)} aria-label="Container">
                {source.containers.map((c) => <option key={c}>{c}</option>)}</Select></Field>}
              <Field label="Index name"><Input value={indexName} onChange={(_, d) => setIndexName(d.value)} aria-label="Index name" /></Field>
              {source.kind !== "storage" && <InfoBar intent="warning">Vyomi indexers read Blob data only: the data source and indexer are created, but running the indexer reports the real failure.</InfoBar>}
              <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={busy || !indexName} onClick={importData}>Import data</Button></div>
            </section>
          )}
          {result && (
            <section className="vy-section"><h3>Indexer result</h3>
              <InfoBar intent={result.status === "success" ? "success" : "error"}>
                {result.status === "success" ? `Indexed ${result.itemsProcessed} document(s), ${result.itemsFailed} failed.` : result.errorMessage}
              </InfoBar>
              {result.status === "success" && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                    <Field label="Search explorer query"><Input value={q} onChange={(_, d) => setQ(d.value)} aria-label="Search query" /></Field>
                    <Button onClick={search}>Search</Button>
                  </div>
                  {hits && (
                    <table className="vy-grid" style={{ marginTop: 8 }}>
                      <thead><tr><th>Score</th><th>Name</th><th>Content</th></tr></thead>
                      <tbody>{hits.value.length ? hits.value.map((h) => <tr key={h.id}><td>{h["@search.score"]}</td><td>{h.metadata_storage_name}</td><td>{String(h.content || "").slice(0, 120)}</td></tr>)
                        : <tr><td colSpan={3} className="vy-muted">No documents match.</td></tr>}</tbody>
                    </table>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </CapabilityContainer>
  );
}
