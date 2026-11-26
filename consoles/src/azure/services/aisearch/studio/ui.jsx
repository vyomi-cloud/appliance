/* Small Fluent-based building blocks for the Azure RAG Studio (the AWS Studio uses Cloudscape; this console has its own kit). */
import { Badge, Button, MessageBar, MessageBarBody, MessageBarTitle, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";

export const Card = ({ title, description, actions, children, testid }) => (
  <section data-testid={testid} style={{ border: "1px solid var(--colorNeutralStroke2, #d1d1d1)", borderRadius: 6, padding: 16, background: "var(--colorNeutralBackground1, #fff)" }}>
    {(title || actions) && <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
      <div><h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>{description && <div style={{ fontSize: 12, opacity: 0.75, marginTop: 2, maxWidth: 780 }}>{description}</div>}</div>
      {actions && <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div>}
    </div>}
    {children}
  </section>
);
export const Stack = ({ gap = 12, children, row, style }) => <div style={{ display: "flex", flexDirection: row ? "row" : "column", gap, flexWrap: row ? "wrap" : undefined, ...style }}>{children}</div>;
export const Grid = ({ cols = 2, children, gap = 16 }) => <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap }}>{children}</div>;
export const Tile = ({ label, value, id }) => <div><div style={{ fontSize: 12, opacity: 0.7 }}>{label}</div><div data-testid={id} style={{ fontSize: 26, fontWeight: 600 }}>{value}</div></div>;
export const Alert = ({ type = "info", title, children, ...rest }) => (
  <MessageBar intent={type === "error" ? "error" : type === "warning" ? "warning" : type === "success" ? "success" : "info"} {...rest}>
    <MessageBarBody>{title && <MessageBarTitle>{title}</MessageBarTitle>}{children}</MessageBarBody>
  </MessageBar>
);
export const Status = ({ type = "info", children }) => <Badge appearance="tint" color={{ success: "success", error: "danger", warning: "warning", info: "informative", stopped: "subtle" }[type] || "informative"}>{children}</Badge>;
export const Btn = ({ children, primary, ...p }) => <Button appearance={primary ? "primary" : "secondary"} {...p}>{children}</Button>;

/** columns: [{id, header, cell(row), width?}] */
export function Tbl({ items, columns, trackBy, empty = "No rows.", testid }) {
  if (!items.length) return <div data-testid={testid} style={{ padding: 8, opacity: 0.7 }}>{empty}</div>;
  return (
    <div style={{ overflow: "auto" }}>
      <Table size="small" data-testid={testid} aria-label={testid || "table"}>
        <TableHeader><TableRow>{columns.map((c) => <TableHeaderCell key={c.id} style={c.width ? { width: c.width } : undefined}>{c.header}</TableHeaderCell>)}</TableRow></TableHeader>
        <TableBody>{items.map((r, i) => <TableRow key={trackBy ? r[trackBy] : i}>{columns.map((c) => <TableCell key={c.id}>{c.cell(r)}</TableCell>)}</TableRow>)}</TableBody>
      </Table>
    </div>
  );
}

/** Horizontal bar chart: data = [[label, value]]; yDomain optional max, threshold optional marker. */
export function Bars({ data, max, testid, color = "#0f6cbd", fmt = (v) => v }) {
  const mx = max ?? Math.max(1, ...data.map(([, v]) => v));
  return <div data-testid={testid}>{data.map(([k, v]) => (
    <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, fontSize: 12 }}>
      <span style={{ width: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={k}>{k}</span>
      <div style={{ flex: 1, background: "var(--colorNeutralBackground3, #e9ebed)", height: 10, borderRadius: 5 }}><div style={{ width: `${Math.min(100, (v / mx) * 100)}%`, background: color, height: 10, borderRadius: 5 }} /></div>
      <span style={{ width: 56, textAlign: "right" }}>{fmt(v)}</span>
    </div>))}</div>;
}
export const Pre = ({ children, testid }) => <pre data-testid={testid} style={{ background: "var(--colorNeutralBackground3, #f5f5f5)", padding: 10, fontSize: 11, overflow: "auto", maxHeight: 240, margin: 0 }}>{children}</pre>;
export const Label = ({ label, children, hint }) => <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}><span style={{ fontWeight: 600 }}>{label}</span>{children}{hint && <span style={{ fontSize: 11, opacity: 0.7 }}>{hint}</span>}</label>;
