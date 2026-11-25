/* RolePicker: the "Role" tab of Add role assignment. Searchable list of every built-in role (507 verbatim, catalog _roles) + custom roles,
 * sub-tabs "Job function roles" / "Privileged administrator roles", Type + Category filters, a "View" link per role opening
 * Permissions (Actions / NotActions / DataActions / NotDataActions) and JSON tabs. */
import { useMemo, useState } from "react";
import { Button, Link, Radio, SearchBox, Select, Spinner, Tab, TabList } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import Blade from "./Blade.jsx";
import { CATEGORY_LABEL, isPrivileged, loadRoles } from "./data.js";

export function RolePermissions({ role }) {
  const [t, setT] = useState("perm");
  const sec = (title, list) => (
    <section className="vy-section" key={title}><h3>{title} ({list.length})</h3>
      {list.length ? <table className="vy-pick-grid"><tbody>{list.map((a) => <tr key={a}><td><code>{a}</code></td></tr>)}</tbody></table> : <span className="vy-muted" style={{ fontSize: 13 }}>None</span>}
    </section>);
  const json = { id: role.id, roleName: role.roleName, description: role.description, type: role.type, permissions: [{ actions: role.actions, notActions: role.notActions, dataActions: role.dataActions, notDataActions: role.notDataActions }], assignableScopes: role.assignableScopes };
  return (
    <div>
      <p style={{ fontSize: 13 }}>{role.description || "No description."}</p>
      <TabList selectedValue={t} onTabSelect={(_, d) => setT(d.value)} aria-label="Role view tabs"><Tab value="perm">Permissions</Tab><Tab value="json">JSON</Tab></TabList>
      {t === "perm" ? <div style={{ marginTop: 12 }}>{sec("Actions", role.actions)}{sec("NotActions", role.notActions)}{sec("DataActions", role.dataActions)}{sec("NotDataActions", role.notDataActions)}</div>
        : <pre className="vy-code" style={{ marginTop: 12 }} data-testid="role-json">{JSON.stringify(json, null, 2)}</pre>}
    </div>
  );
}

export default function RolePicker({ value, onChange, kind = "all" /* "all" | "dataOnly" */ }) {
  const { data, loading, error } = useAsync(loadRoles, []);
  const [sub, setSub] = useState("job");
  const [q, setQ] = useState("");
  const [type, setType] = useState("all");
  const [cat, setCat] = useState("all");
  const [view, setView] = useState(null);
  const base = useMemo(() => (data || []).filter((r) => (sub === "priv" ? isPrivileged(r) : !isPrivileged(r))), [data, sub]);
  const cats = useMemo(() => [...new Set(base.map((r) => r.category))].sort(), [base]);
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return base.filter((r) => (type === "all" || r.type === type) && (cat === "all" || r.category === cat)
      && (!s || r.roleName.toLowerCase().includes(s) || (r.description || "").toLowerCase().includes(s) || r.id.includes(s)));
  }, [base, q, type, cat]);
  if (loading) return <div style={{ padding: 16 }}><Spinner size="small" label="Loading roles..." /></div>;
  if (error) return <div className="vy-info" role="alert">Could not load roles: {String(error.message || error)}</div>;
  return (
    <div data-testid="role-picker">
      <p style={{ fontSize: 13 }}>A role definition is a collection of permissions. You can use the built-in roles or you can create your own custom roles.</p>
      <TabList selectedValue={sub} onTabSelect={(_, d) => setSub(d.value)} aria-label="Role type tabs"><Tab value="job">Job function roles</Tab><Tab value="priv">Privileged administrator roles</Tab></TabList>
      <p style={{ fontSize: 13 }}>{sub === "job" ? "Grant permissions to a specific job function, such as managing storage or reading data." : "Grant privileged administrator access, such as the ability to assign roles to other users or manage all resources."}</p>
      <div style={{ display: "flex", gap: 12, alignItems: "center", margin: "8px 0", flexWrap: "wrap" }}>
        <SearchBox style={{ width: 340 }} placeholder="Search by role name, description, or ID" aria-label="Search by role name, description, or ID" value={q} onChange={(_, d) => setQ(d.value)} />
        <Select aria-label="Type" value={type} onChange={(_, d) => setType(d.value)}><option value="all">Type : All</option><option value="BuiltInRole">Type : Built-in</option><option value="CustomRole">Type : Custom</option></Select>
        <Select aria-label="Category" value={cat} onChange={(_, d) => setCat(d.value)}><option value="all">Category : All</option>{cats.map((c) => <option key={c} value={c}>Category : {CATEGORY_LABEL(c)}</option>)}</Select>
      </div>
      <div className="vy-muted" style={{ fontSize: 12, margin: "4px 0" }}>Showing {rows.length} of {base.length} roles</div>
      <div style={{ maxHeight: "48vh", overflow: "auto" }}>
        <table className="vy-pick-grid" aria-label="Roles">
          <thead><tr><th style={{ width: 32 }} /><th>Name</th><th>Description</th><th>Type</th><th>Category</th><th>Details</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={value?.id === r.id ? "sel" : ""} onClick={() => onChange(r)} style={{ cursor: "pointer" }} data-testid={`role-row-${r.roleName}`}>
                <td onClick={(e) => e.stopPropagation()}><Radio checked={value?.id === r.id} onChange={() => onChange(r)} aria-label={`Select ${r.roleName}`} label="" /></td>
                <td>{r.roleName}</td><td>{r.description}</td><td>{r.type === "CustomRole" ? "CustomRole" : "BuiltInRole"}</td><td>{CATEGORY_LABEL(r.category)}</td>
                <td><Link as="button" onClick={(e) => { e.stopPropagation(); setView(r); }} aria-label={`View ${r.roleName}`}>View</Link></td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={6} className="vy-muted">No roles match.</td></tr>}
          </tbody>
        </table>
      </div>
      {view && <Blade level={2} width="min(820px,100vw)" title={view.roleName} subtitle="Role definition" onClose={() => setView(null)}
        footer={<><Button appearance="primary" onClick={() => { onChange(view); setView(null); }}>Select</Button><Button onClick={() => setView(null)}>Close</Button></>}>
        <RolePermissions role={view} /></Blade>}
    </div>
  );
}
