/* "Notices & licences" page, shared by the AWS, GCP and Azure consoles (route #/notices). Renders consoles/src/common/third-party-notices.json,
 * GENERATED from tools/notices/notices.json by tools/notices/gen_notices.py. Cloud-neutral markup so it sits in all three shells.
 * ENGINEERING DRAFT: not legal advice; counsel must review before paid hosting (docs/architecture/v4.0/AI-LICENCE-AUDIT.md). */
import N from "./third-party-notices.json";
import { AI_MODELS, AI_SPECIAL } from "./aiModels.js";
import { shortLicense } from "./LicenceChip.jsx";

const BORDER = "1px solid color-mix(in srgb, currentColor 18%, transparent)";
const H2 = ({ children }) => <h2 style={{ fontSize: 18, fontWeight: 600, margin: "24px 0 8px" }}>{children}</h2>;
const TH = { textAlign: "left", padding: "6px 8px", borderBottom: BORDER, fontWeight: 600, verticalAlign: "bottom" };
const TD = { padding: "6px 8px", borderBottom: BORDER, verticalAlign: "top" };
const A = ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "underline" }}>{children}</a>;

function Table({ cols, rows, testid }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table data-testid={testid} style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <thead><tr>{cols.map((c) => <th key={c} style={TH}>{c}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} style={TD}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export default function NoticesPage() {
  const here = new Set([...AI_MODELS, ...AI_SPECIAL].map((m) => m.id));
  const used = new Set(N.models.map((m) => m.licenseId));
  const blob = (f) => N.repoBlob + f;
  return (
    <div data-testid="notices-page" style={{ maxWidth: 1100, fontSize: 14, lineHeight: 1.5, padding: "8px 0 40px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, margin: "8px 0" }}>Notices and licences</h1>
      <div role="note" data-testid="notices-draft" style={{ border: BORDER, borderLeft: "4px solid #b26a00", padding: "8px 12px", margin: "8px 0 16px" }}>{N.draftBanner}</div>
      <p data-testid="notices-disclaimer" style={{ margin: "0 0 8px" }}>{N.disclaimer}</p>
      <p style={{ margin: "0 0 8px" }}>Vyomi runs open models and open-source software. Each keeps its own licence. Nothing here implies that the model makers or any cloud vendor endorse Vyomi.</p>
      <p style={{ margin: 0 }}>
        Policies that also apply to your use of Vyomi: <A href={N.links.gemmaProhibitedUse}>Gemma Prohibited Use Policy</A>, <A href={N.links.llamaAup31}>Llama 3.1 Acceptable Use Policy</A> and <A href={N.links.llamaAup32}>Llama 3.2 Acceptable Use Policy</A>.
      </p>

      <H2>Models</H2>
      {N.models.some((m) => m.builtWithLlama) && <p data-testid="notices-built-with-llama" style={{ fontWeight: 700 }}>Built with Llama</p>}
      <Table testid="notices-models" cols={["Model", "Licence", "Copyright holder", "Commercial use", "In this build"]}
        rows={N.models.map((m) => [
          <span key="n"><b>{m.name}</b><br /><code>{m.id}</code>{m.note ? <><br /><span style={{ opacity: 0.8 }}>{m.note}</span></> : null}</span>,
          <span key="l"><A href={m.licenseUrl}>{shortLicense(m)}</A>{m.aupUrl ? <><br /><A href={m.aupUrl}>Use policy</A></> : null}</span>,
          <span key="c"><A href={m.upstream}>{m.copyright}</A></span>,
          m.commercialUse ? "Yes" : <b key="f" style={{ color: "#b3261e" }}>{m.flag}</b>,
          here.has(m.id) ? "Yes" : "No (other substrate)",
        ])} />

      <H2>Required notices</H2>
      {Object.entries(N.licences).filter(([, l]) => used.has(l.spdx) && l.notice).map(([k, l]) => (
        <section key={k} data-testid={`notice-${k}`} style={{ margin: "0 0 12px" }}>
          <div style={{ fontWeight: 600 }}>{l.name}</div>
          {l.builtWith && <div style={{ fontWeight: 700 }}>{l.builtWith}</div>}
          <div>{l.notice}</div>
          {l.flag && <div style={{ color: "#b3261e", fontWeight: 600 }}>{l.flag}</div>}
          {l.namingRule && <div style={{ opacity: 0.85 }}>Naming rule: {l.namingRule}</div>}
          <div><A href={l.url}>Licence text</A>{l.aupUrl ? <> &middot; <A href={l.aupUrl}>Use policy</A></> : null}{l.file ? <> &middot; <A href={blob(l.file)}>copy in the repository</A></> : null}</div>
        </section>
      ))}
      <p>Apache-2.0 and MIT models: the licence text and any upstream NOTICE are kept; the copyright holder and source are in the table above. DeepSeek R1 models are MIT and derived from Qwen (Apache-2.0).</p>

      <H2>Software</H2>
      <Table testid="notices-components" cols={["Component", "Version", "Licence", "Copyright holder", "Notes"]}
        rows={N.components.map((c) => [<A key="n" href={c.upstream}>{c.name}</A>, c.version || "", c.license, c.copyright, c.note])} />
      <p style={{ marginTop: 12 }}>{N.npm.count} JavaScript packages are bundled into the consoles ({Object.entries(N.npm.byLicense).map(([l, n]) => `${l}: ${n}`).join(", ")}). Each keeps its own copyright notice.</p>

      <H2>Full lists and licence texts</H2>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        <li><A href={blob("THIRD-PARTY-NOTICES.md")}>THIRD-PARTY-NOTICES.md</A>: the complete third-party list including every JavaScript package.</li>
        <li><A href={blob("sbom.cdx.json")}>sbom.cdx.json</A>: software bill of materials (CycloneDX).</li>
        <li><A href={blob("licenses/")}>licenses/</A>: full licence texts. <A href={N.links.minioSource}>MinIO</A> is used under AGPL v3: the corresponding source is the upstream tag plus the build recipe in the repository.</li>
      </ul>
    </div>
  );
}
