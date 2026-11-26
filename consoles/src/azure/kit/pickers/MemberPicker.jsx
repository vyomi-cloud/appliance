/* MemberPicker: the portal's "Add assignments"/"Select members" blade. Left: info bar, Search (with info icon), result count, tabs
 * All | Users | Groups | Service principals | Managed identities, table Name | Type | Details (avatar + checkbox). Right pane:
 * "Selected (n)", Reset, "No items selected". Blue Add button. Fed from the Entra directory store (Microsoft Graph). */
import { useMemo, useState } from "react";
import { Button, Checkbox, Input, Spinner, Tab, TabList, Tooltip } from "@fluentui/react-components";
import { ArrowUndo20Regular, Dismiss16Regular, Info16Regular, Info20Regular, Search20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import Blade from "./Blade.jsx";
import { loadDirectory } from "./data.js";

const COLORS = ["#ca5010", "#0078d4", "#8764b8", "#038387", "#986f0b", "#498205", "#c239b3"];
export const initials = (n) => String(n || "?").split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";
export const Avatar = ({ name, id }) => <span className="vy-avatar" style={{ background: COLORS[[...String(id || name)].reduce((a, c) => a + c.charCodeAt(0), 0) % COLORS.length] }} aria-hidden>{initials(name)}</span>;

const TABS = [["all", "All", () => true], ["user", "Users", (m) => m.type === "User"], ["group", "Groups", (m) => m.type === "Group"],
  ["sp", "Service principals", (m) => m.type === "Service principal"], ["mi", "Managed identities", (m) => m.type === "Managed identity"]];

/** kind: "principals" (user, group, service principal) | "mi" (managed identities only). multiple: false for single-select (Check access). */
export default function MemberPicker({ title = "Select members", kind = "principals", multiple = true, initial = [], onAdd, onClose, addLabel = "Add" }) {
  const { data, loading, error } = useAsync(loadDirectory, []);
  const [q, setQ] = useState("");
  const [tab, setTab] = useState("all");
  const [sel, setSel] = useState(initial);
  const pool = useMemo(() => (data || []).filter((m) => (kind === "mi" ? m.managed : !m.managed)), [data, kind]);
  const tabs = kind === "mi" ? [] : TABS.filter((t) => t[0] !== "mi");
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase(); const f = (TABS.find((t) => t[0] === tab) || TABS[0])[2];
    return pool.filter(f).filter((m) => !s || m.name?.toLowerCase().includes(s) || m.details?.toLowerCase().includes(s) || m.id.toLowerCase().includes(s));
  }, [pool, q, tab]);
  const has = (m) => sel.some((x) => x.id === m.id);
  const toggle = (m) => setSel((s) => (has(m) ? s.filter((x) => x.id !== m.id) : multiple ? [...s, m] : [m]));
  return (
    <Blade level={2} title={title} onClose={onClose} width="min(1280px, 100vw)" testid="member-picker" label="Select members"
      footer={<Button appearance="primary" onClick={() => onAdd(sel)}>{addLabel}</Button>}>
      <div className="vy-members">
        <div className="vy-mleft">
          <div className="vy-info"><Info20Regular style={{ color: "var(--colorBrandForeground1)" }} /> Try changing or adding filters if you don't see what you're looking for.</div>
          <label htmlFor="vy-mp-search" style={{ fontSize: 14, display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>Search
            <Tooltip relationship="description" content="Search by display name, user principal name, or object ID."><Info16Regular /></Tooltip></label>
          <Input id="vy-mp-search" style={{ width: "100%" }} contentBefore={<Search20Regular />} value={q} onChange={(_, d) => setQ(d.value)} aria-label="Search" />
          <div style={{ fontSize: 14, margin: "6px 8px" }} aria-live="polite">{loading ? "Searching..." : `${rows.length} result${rows.length === 1 ? "" : "s"} found`}</div>
          {tabs.length > 0 && <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Member type tabs">{tabs.map((t) => <Tab key={t[0]} value={t[0]}>{t[1]}</Tab>)}</TabList>}
          {loading && <Spinner size="small" />}
          {error && <div className="vy-info" role="alert">Could not load the directory: {String(error.message || error)}</div>}
          <div role="table" aria-label="Members" style={{ marginTop: 12 }}>
            <div className="vy-mrow head" role="row"><span /><span /><span>Name</span><span>Type</span><span>Details</span></div>
            {rows.map((m) => (
              <div className="vy-mrow" role="row" key={m.id} onClick={() => toggle(m)} style={{ cursor: "pointer" }} data-testid={`member-row-${m.name}`}>
                <span onClick={(e) => e.stopPropagation()}><Checkbox checked={has(m)} onChange={() => toggle(m)} aria-label={`Select ${m.name}`} /></span>
                <Avatar name={m.name} id={m.id} /><span>{m.name}</span><span>{m.type}</span><span style={{ overflowWrap: "anywhere" }}>{m.details}</span>
              </div>
            ))}
            {!loading && !rows.length && <div className="vy-muted" style={{ padding: 12 }}>No results.</div>}
          </div>
        </div>
        <aside className="vy-mright" aria-label="Selected members">
          <h2>Selected ({sel.length})</h2>
          <Button appearance="transparent" icon={<ArrowUndo20Regular />} onClick={() => setSel([])} style={{ color: "var(--colorBrandForegroundLink)" }}>Reset</Button>
          {sel.length === 0 ? <p style={{ marginTop: 24, fontSize: 14 }}>No items selected</p> : (
            <div style={{ marginTop: 12 }}>{sel.map((m) => (
              <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
                <Avatar name={m.name} id={m.id} /><div style={{ flex: 1, minWidth: 0, fontSize: 13 }}><div>{m.name}</div><div className="vy-muted" style={{ overflowWrap: "anywhere" }}>{m.details}</div></div>
                <Button appearance="subtle" size="small" icon={<Dismiss16Regular />} aria-label={`Remove ${m.name}`} onClick={() => toggle(m)} />
              </div>))}</div>)}
        </aside>
      </div>
    </Blade>
  );
}
