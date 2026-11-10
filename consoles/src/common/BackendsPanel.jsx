/* "How Vyomi runs this service" section for the help / info side panel of every v4 console.
 * Cloud-neutral markup (plain elements, inherited font and colours, currentColor borders) so it
 * sits naturally in Cloudscape's HelpPanel, Fluent's drawer and the GCP MUI aside; only the
 * accent colour is per cloud. Data helpers live in ./backends.js. */
import { useEffect, useState } from "react";
import { KIND_LABEL, LEVELS, backendInfo, fidelity } from "./backends.js";

const SEG = { full: "#2e8540", limited: "#3b82c4", config_only: "#d9a21b", not_simulated: "#8a8f98" };
const line = "color-mix(in srgb, currentColor 22%, transparent)";
const soft = "color-mix(in srgb, currentColor 8%, transparent)";

function Chip({ children }) {
  return <span style={{ display: "inline-block", padding: "1px 8px", margin: "0 6px 6px 0", border: `1px solid ${line}`, borderRadius: 10, fontSize: 12, background: soft }}>{children}</span>;
}
const H = ({ children }) => <div style={{ fontWeight: 600, fontSize: 13, margin: "14px 0 4px" }}>{children}</div>;
const List = ({ items }) => <ul style={{ margin: 0, paddingLeft: 18 }}>{items.map((x, i) => <li key={i} style={{ marginBottom: 3 }}>{x}</li>)}</ul>;
const arr = (x) => (Array.isArray(x) ? x.filter((s) => typeof s === "string" && s) : []);

export function FidelityBar({ fid }) {
  if (!fid) return <div style={{ fontSize: 12, opacity: 0.8 }}>No capability registry for this service on this substrate.</div>;
  return (
    <div data-testid="backends-fidelity">
      <div role="img" aria-label={LEVELS.map(([k, l]) => `${fid.counts[k]} ${l}`).join(", ")} style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", background: soft }}>
        {LEVELS.map(([k]) => fid.counts[k] > 0 && <span key={k} style={{ width: `${(100 * fid.counts[k]) / fid.total}%`, background: SEG[k] }} />)}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 12px", marginTop: 6, fontSize: 12 }}>
        {LEVELS.map(([k, l]) => (
          <span key={k} style={{ whiteSpace: "nowrap" }}><span aria-hidden style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: SEG[k], marginRight: 5 }} />{fid.counts[k]} {l}</span>
        ))}
      </div>
      <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>{fid.total} features in the capability registry</div>
    </div>
  );
}

/** props: cloud, data (backends JSON), serviceId, registryFile (that service's registry JSON or null),
 *  substrate ("offline"|"nano" — the running one), accent (CSS colour). */
export default function BackendsSection({ cloud, data, serviceId, registryFile, substrate, accent = "#0b6cbd" }) {
  const [sub, setSub] = useState(substrate === "nano" ? "nano" : "offline");
  useEffect(() => { setSub(substrate === "nano" ? "nano" : "offline"); }, [serviceId, substrate]);
  if (!serviceId) return null;
  const info = backendInfo(data, serviceId);
  const box = { border: `1px solid ${line}`, borderRadius: 8, padding: "12px 14px", marginBottom: 16, fontSize: 13, lineHeight: 1.5 };
  const head = <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>How Vyomi runs this service</div>;
  if (!info) {
    return <section data-testid="backends-section" data-service={serviceId} style={box}>{head}<div data-testid="backends-missing" style={{ opacity: 0.85 }}>Backend details for this service are not documented yet.</div></section>;
  }
  const side = (info[sub] && typeof info[sub] === "object") ? info[sub] : null;
  const wire = arr(info.wire), differs = arr(info.differs), notIn = arr(info.notInScope), sources = arr(info.sources), tech = arr(side?.tech);
  const tab = (id, label) => (
    <button key={id} type="button" role="tab" aria-selected={sub === id} onClick={() => setSub(id)} data-testid={`backends-tab-${id}`}
      style={{ flex: 1, padding: "5px 8px", font: "inherit", fontSize: 12, cursor: "pointer", color: "inherit", border: `1px solid ${sub === id ? accent : line}`, background: sub === id ? `color-mix(in srgb, ${accent} 16%, transparent)` : "transparent", fontWeight: sub === id ? 700 : 400, borderRadius: id === "offline" ? "6px 0 0 6px" : "0 6px 6px 0" }}>{label}</button>
  );
  return (
    <section data-testid="backends-section" data-service={serviceId} data-cloud={cloud} style={box}>
      {head}
      {info.title && <div style={{ fontWeight: 600 }}>{info.title}</div>}
      {info.summary && <p style={{ margin: "4px 0 10px" }}>{info.summary}</p>}
      <div role="tablist" aria-label="Substrate" style={{ display: "flex", marginBottom: 10 }}>{tab("offline", "Offline appliance")}{tab("nano", "Nano")}</div>
      <div data-testid="backends-substrate" data-substrate={sub}>
        {side ? (
          <>
            <span data-testid="backends-kind" style={{ display: "inline-block", padding: "2px 10px", borderRadius: 10, fontSize: 12, fontWeight: 600, color: "#fff", background: side.kind === "unavailable" ? "#6b7078" : accent }}>{KIND_LABEL[side.kind] || "Unspecified"}</span>
            {tech.length > 0 && <div style={{ marginTop: 8 }}>{tech.map((t) => <Chip key={t}>{t}</Chip>)}</div>}
            {side.notes && <p style={{ margin: "4px 0 0" }}>{side.notes}</p>}
          </>
        ) : <div style={{ opacity: 0.85 }}>Not documented yet for this substrate.</div>}
      </div>
      {wire.length > 0 && <><H>Works unchanged with</H><div>{wire.map((w) => <Chip key={w}>{w}</Chip>)}</div></>}
      <H>{`Fidelity on ${sub === "nano" ? "Nano" : "the offline appliance"}`}</H>
      <FidelityBar fid={fidelity(registryFile, sub)} />
      {differs.length > 0 && <><H>Differs from the real cloud</H><List items={differs} /></>}
      {notIn.length > 0 && <><H>Out of scope</H><List items={notIn} /></>}
      {sources.length > 0 && (
        <details style={{ marginTop: 12 }} data-testid="backends-sources">
          <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 13 }}>Sources ({sources.length})</summary>
          <div style={{ marginTop: 6 }}>{sources.map((s, i) => /^https?:\/\//.test(s)
            ? <div key={i} style={{ wordBreak: "break-all" }}><a href={s} target="_blank" rel="noopener noreferrer">{s}</a></div>
            : <div key={i} style={{ wordBreak: "break-all" }}>{s}</div>)}</div>
        </details>
      )}
    </section>
  );
}
