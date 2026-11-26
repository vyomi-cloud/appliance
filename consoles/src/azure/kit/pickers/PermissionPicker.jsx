/* PermissionPicker: "Add permissions" of the custom-role wizard. Step 1 searches a resource provider by name (e.g. Microsoft.Storage);
 * step 2 lists that provider's Actions and Data actions (verbatim catalog, core/iam_catalog/azure/<provider>.json) grouped by resource
 * type with a search filter and checkboxes. `single` = pick exactly one action (Check access / Effective access / ABAC). */
import { useMemo, useState } from "react";
import { Button, Checkbox, Link, SearchBox, Spinner, Tab, TabList } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import Blade from "./Blade.jsx";
import { PROVIDERS, loadProviderCatalog } from "./data.js";

/** "Microsoft.Storage/storageAccounts/blobServices/containers/read" -> group "Microsoft.Storage/storageAccounts/blobServices/containers" */
const groupOf = (a) => { const i = a.lastIndexOf("/"); return i > 0 ? a.slice(0, i) : a; };

export function ProviderActions({ provider, selected, onToggle, plane, onPlane, single }) {
  const cat = useAsync(() => loadProviderCatalog(provider), [provider]);
  const [q, setQ] = useState("");
  const map = plane === "data" ? cat.data?.dataActions : cat.data?.actions;
  const groups = useMemo(() => {
    const s = q.trim().toLowerCase(); const g = {};
    for (const [a, d] of Object.entries(map || {})) if (!s || a.toLowerCase().includes(s) || (d || "").toLowerCase().includes(s)) (g[groupOf(a)] ||= []).push([a, d]);
    return Object.entries(g).sort((x, y) => x[0].localeCompare(y[0]));
  }, [map, q]);
  if (cat.loading) return <Spinner size="small" label="Loading catalog..." />;
  if (cat.error) return <div className="vy-info" role="alert">No permission catalog for {provider}: {String(cat.error.message || cat.error)}</div>;
  const has = (a) => selected.includes(a);
  const nA = Object.keys(cat.data?.actions || {}).length, nD = Object.keys(cat.data?.dataActions || {}).length;
  return (
    <div data-testid="permission-list">
      <TabList selectedValue={plane} onTabSelect={(_, d) => onPlane(d.value)} aria-label="Action plane tabs"><Tab value="actions">Actions ({nA})</Tab><Tab value="data">Data actions ({nD})</Tab></TabList>
      <SearchBox style={{ width: "100%", margin: "10px 0" }} placeholder="Search for an action" aria-label="Search for an action" value={q} onChange={(_, d) => setQ(d.value)} />
      <div style={{ maxHeight: "46vh", overflow: "auto" }}>
        {groups.map(([g, list]) => (
          <section key={g} style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center", fontWeight: 600, fontSize: 13, background: "var(--colorNeutralBackground3)", padding: "4px 8px" }}>
              <span>{g}</span>
              {!single && <Link as="button" onClick={() => list.filter(([a]) => !has(a)).forEach(([a]) => onToggle(a))}>Select all</Link>}
            </div>
            {list.map(([a, d]) => (
              <div key={a} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "3px 8px", fontSize: 13 }}>
                <Checkbox checked={has(a)} onChange={() => onToggle(a)} aria-label={a} />
                <div><code>{a}</code><div className="vy-muted">{d}</div></div>
              </div>
            ))}
          </section>
        ))}
        {!groups.length && <p className="vy-muted">No {plane === "data" ? "data actions" : "actions"} match.</p>}
      </div>
    </div>
  );
}

export default function PermissionPicker({ onAdd, onClose, single = false, title }) {
  const [q, setQ] = useState("");
  const [provider, setProvider] = useState(null);
  const [plane, setPlane] = useState("actions");
  const [sel, setSel] = useState({ actions: [], data: [] });
  const matches = PROVIDERS.filter((p) => p.toLowerCase().includes(q.trim().toLowerCase()));
  const toggle = (a) => setSel((s) => { const k = plane; const cur = s[k]; return single ? { actions: [], data: [], [k]: cur.includes(a) ? [] : [a] } : { ...s, [k]: cur.includes(a) ? cur.filter((x) => x !== a) : [...cur, a] }; });
  const total = sel.actions.length + sel.data.length;
  return (
    <Blade level={2} title={title || (single ? "Select an action" : "Add permissions")} subtitle={provider ? undefined : "Search for a resource provider by name"} onClose={onClose} width="min(900px,100vw)" testid="permission-picker"
      footer={<><Button appearance="primary" disabled={!total} onClick={() => onAdd(sel)}>{single ? "Select" : "Add"}</Button><Button onClick={onClose}>Cancel</Button></>}>
      {!provider ? (
        <div style={{ marginTop: 12 }}>
          <SearchBox style={{ width: "100%" }} placeholder="Search for a Microsoft.Provider name" aria-label="Search for a resource provider" value={q} onChange={(_, d) => setQ(d.value)} />
          <table className="vy-pick-grid" style={{ marginTop: 8 }} aria-label="Resource providers"><tbody>
            {matches.map((p) => <tr key={p} onClick={() => setProvider(p)} style={{ cursor: "pointer" }} data-testid={`provider-${p}`}><td>{p}</td></tr>)}
            {q.trim() && !PROVIDERS.some((p) => p.toLowerCase() === q.trim().toLowerCase()) && <tr onClick={() => setProvider(q.trim())} style={{ cursor: "pointer" }}><td>Use "{q.trim()}" (may have no catalog)</td></tr>}
          </tbody></table>
        </div>
      ) : (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 8 }}><b>{provider}</b><Link as="button" onClick={() => setProvider(null)}>Change provider</Link><span className="vy-muted">{total} selected</span></div>
          <ProviderActions provider={provider} selected={sel[plane]} onToggle={toggle} plane={plane} onPlane={setPlane} single={single} />
        </div>
      )}
    </Blade>
  );
}
