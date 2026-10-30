/* Shared Azure-lens pieces: honest "not simulated" state, Essentials grid, key/value rows,
 * error bar, formatting. */
import { useState } from "react";
import { MessageBar, MessageBarBody, MessageBarTitle, Link, Spinner } from "@fluentui/react-components";
import { ChevronDown16Regular, ChevronRight16Regular } from "@fluentui/react-icons";

/** A feature the real portal has but Vyomi does not back with a real backend. The
 *  data-vyomi-not-simulated attribute is the UI-conformance contract (same as the AWS lens):
 *  elements inside count as a declared gap, never as present. */
export function NotSimulated({ feature, note }) {
  return (
    <div className="vy-ns" data-vyomi-not-simulated={feature} role="note">
      <span className="vy-ns-badge">Not simulated in Vyomi</span>
      <div>{feature} isn't backed by a Vyomi backend yet.</div>
      {note && <div style={{ marginTop: 6, fontSize: 12 }}>{note}</div>}
    </div>
  );
}

export function NotSimulatedContainer({ title, feature, note }) {
  return (
    <section className="vy-ns-container" data-vyomi-gap-box="">
      {title && <h3>{title}</h3>}
      <NotSimulated feature={feature || title} note={note} />
    </section>
  );
}

/** The Overview "Essentials" block: two columns of label : value, collapsible, with an
 *  optional "JSON View" action on the right. */
export function Essentials({ left = [], right = [], actions }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="vy-essentials">
      <div style={{ display: "flex", alignItems: "center" }}>
        <button className="vy-essentials-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? <ChevronDown16Regular /> : <ChevronRight16Regular />} Essentials
        </button>
        <span style={{ marginLeft: "auto" }}>{actions}</span>
      </div>
      {open && (
        <div className="vy-essentials-grid">
          <div>{left.map(([k, v]) => <KV key={k} label={k} value={v} />)}</div>
          <div>{right.map(([k, v]) => <KV key={k} label={k} value={v} />)}</div>
        </div>
      )}
    </div>
  );
}

export const KV = ({ label, value }) => (
  <div className="vy-kv"><span>{label}</span><span>{value === undefined || value === null || value === "" ? "--" : value}</span></div>
);

export const ErrorBar = ({ error, title }) => error ? (
  <MessageBar intent="error" style={{ margin: "8px 0" }}>
    <MessageBarBody><MessageBarTitle>{title || error.code || "Error"}</MessageBarTitle>{error.message}</MessageBarBody>
  </MessageBar>
) : null;

export const InfoBar = ({ children, intent = "info", title }) => (
  <MessageBar intent={intent} style={{ margin: "8px 0" }}>
    <MessageBarBody>{title && <MessageBarTitle>{title}</MessageBarTitle>}{children}</MessageBarBody>
  </MessageBar>
);

export const Loading = ({ label = "Loading..." }) => <div style={{ padding: 32 }}><Spinner size="small" label={label} /></div>;

/** Neutral initials glyph in place of a service icon (no Microsoft icons in Vyomi). */
export const Glyph = ({ text, color, size = 32 }) => (
  <span className="vy-glyph" aria-hidden style={{ "--vy-glyph": color, width: size, height: size, fontSize: size < 28 ? 10 : 13 }}>{text}</span>
);

export const fmtDate = (v) => {
  if (!v) return "--";
  const d = new Date(v);
  return isNaN(d) ? String(v) : d.toLocaleString(undefined, { month: "numeric", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
};

export const fmtBytes = (n) => {
  n = Number(n || 0);
  const u = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(2) : n} ${u[i]}`;
};

export const RouteLink = ({ to, children, ...rest }) => <Link href={to} {...rest}>{children}</Link>;

/** Download rows as CSV (the browse grid's "Export to CSV"). */
export function downloadCsv(filename, columns, rows) {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const text = [columns.map((c) => esc(c.label)).join(","), ...rows.map((r) => columns.map((c) => esc(c.csv ? c.csv(r) : r[c.key])).join(","))].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
