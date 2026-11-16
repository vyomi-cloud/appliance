/* Renders a scopeHelp entry as plain, cloud-neutral markup (inherits font and colour) so it sits in Cloudscape's HelpPanel,
 * Fluent's drawer and the GCP MUI aside. Always starts with a "Scope and limits" heading. */
const H = ({ children }) => <div style={{ fontWeight: 600, fontSize: 13, margin: "12px 0 4px" }}>{children}</div>;
const List = ({ items }) => <ul style={{ margin: 0, paddingLeft: 18 }}>{items.map((x, i) => <li key={i} style={{ marginBottom: 4 }}>{x}</li>)}</ul>;

export default function ScopeSection({ entry, showTitle = true }) {
  if (!entry) return null;
  const blocks = [["What is real here", entry.real], ["Metadata only", entry.metadata], ["Limits", entry.limits], ["Nano (browser)", entry.nano], ["Mesh / offline", entry.mesh]];
  return (
    <section data-testid="scope-limits" aria-label="Scope and limits" style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 14, paddingBottom: 6, borderBottom: "1px solid color-mix(in srgb, currentColor 18%, transparent)" }}>
      <div style={{ fontWeight: 700, fontSize: 15 }}>Scope and limits</div>
      {showTitle && <div style={{ opacity: 0.8, fontSize: 12 }}>{entry.title.replace(/: scope and limits$/, "")}</div>}
      <p style={{ margin: "6px 0 0" }}>{entry.intro}</p>
      {blocks.map(([h, items]) => items?.length ? <div key={h}><H>{h}</H><List items={items} /></div> : null)}
    </section>
  );
}
