/* App Configuration | Import/export — bulk move key-values between this store and a file
 * (JSON / .properties / simple YAML), an App Service or Function App's application settings, or
 * another configuration store. All through the real data plane (/kv) and the real Microsoft.Web
 * ARM calls, so what an import writes the az CLI / SDK reads back. */
import { useState } from "react";
import { Button, Field, Input, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { InfoBar, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";
import * as webApi from "../appservices/api.js";

const CAP = "azure.appconfiguration.importexport";

// ── (de)serialisers ─────────────────────────────────────────────────────────────────────
function flatten(obj, sep, depth, prefix = "", out = {}, level = 1) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? prefix + sep + k : k;
    if (v && typeof v === "object" && !Array.isArray(v) && (!depth || level < depth)) flatten(v, sep, depth, key, out, level + 1);
    else out[key] = v === null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
  }
  return out;
}
export function parseYaml(text) {
  const root = {}; const stack = [[-1, root]];
  for (const raw of text.split(/\r?\n/)) {
    if (!raw.trim() || raw.trim().startsWith("#")) continue;
    const indent = raw.match(/^ */)[0].length; const m = raw.trim().match(/^([^:]+):\s*(.*)$/);
    if (!m) throw new Error(`Unsupported YAML line: ${raw.trim()}`);
    while (stack.length > 1 && stack[stack.length - 1][0] >= indent) stack.pop();
    const parent = stack[stack.length - 1][1]; const v = m[2].replace(/^["']|["']$/g, "");
    if (m[2] === "") { parent[m[1].trim()] = {}; stack.push([indent, parent[m[1].trim()]]); } else parent[m[1].trim()] = v;
  }
  return root;
}
export function parseProperties(text) {
  const out = {};
  for (const l of text.split(/\r?\n/)) { const t = l.trim(); if (!t || t.startsWith("#") || t.startsWith("!")) continue; const i = t.search(/[=:]/); if (i < 0) continue; out[t.slice(0, i).trim()] = t.slice(i + 1).trim(); }
  return out;
}
export function parseFile(name, text, sep, depth) {
  const lower = name.toLowerCase();
  if (lower.endsWith(".json")) return flatten(JSON.parse(text), sep, depth);
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return flatten(parseYaml(text), sep, depth);
  return parseProperties(text);
}
export function unflatten(flat, sep) {
  const out = {};
  for (const [k, v] of Object.entries(flat)) {
    const parts = sep ? k.split(sep) : [k]; let cur = out;
    parts.forEach((p, i) => { if (i === parts.length - 1) cur[p] = v; else { if (typeof cur[p] !== "object") cur[p] = {}; cur = cur[p]; } });
  }
  return out;
}
const toYaml = (o, ind = 0) => Object.entries(o).map(([k, v]) => (v && typeof v === "object" ? `${" ".repeat(ind)}${k}:\n${toYaml(v, ind + 2)}` : `${" ".repeat(ind)}${k}: ${JSON.stringify(String(v))}`)).join("\n");
export function serialise(flat, format, sep) {
  if (format === "properties") return Object.entries(flat).map(([k, v]) => `${k}=${v}`).join("\n") + "\n";
  const tree = unflatten(flat, sep);
  return format === "yaml" ? toYaml(tree) + "\n" : JSON.stringify(tree, null, 2) + "\n";
}

const download = (name, text) => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" })); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); };

export default function ImportExport({ store }) {
  const notify = useNotify();
  const [mode, setMode] = useState("import");
  const [source, setSource] = useState("file");
  const [format, setFormat] = useState("json");
  const [file, setFile] = useState(null);
  const [app, setApp] = useState(""); const [other, setOther] = useState("");
  const [prefix, setPrefix] = useState(""); const [label, setLabel] = useState(""); const [sep, setSep] = useState("."); const [depth, setDepth] = useState("");
  const [contentType, setContentType] = useState(""); const [filterPrefix, setFilterPrefix] = useState(""); const [filterLabel, setFilterLabel] = useState("");
  const [busy, setBusy] = useState(false); const [result, setResult] = useState(null);
  const apps = useAsync(async () => [...(await webApi.SITES.list())].map((s) => ({ id: s.id, name: s.name, rg: s.id.split("/")[4] })), []);
  const stores = useAsync(async () => (await api.listStores()).filter((s) => s.name !== store), [store]);
  const appOf = (id) => apps.data?.find((a) => a.id === id);

  const run = async () => {
    setBusy(true); setResult(null);
    try {
      let n = 0;
      if (mode === "import") {
        let flat;
        if (source === "file") { if (!file) throw new Error("Choose a file to import."); flat = parseFile(file.name, await file.text(), sep || ".", Number(depth) || 0); }
        else if (source === "appservice") { const a = appOf(app); if (!a) throw new Error("Choose an app."); flat = await webApi.getAppSettings(a.rg, a.name); }
        else { if (!other) throw new Error("Choose a configuration store."); flat = Object.fromEntries((await api.dpFor(other, "GET", "/kv", {})).items.filter((i) => !filterLabel || (i.label || "") === filterLabel).map((i) => [i.key, i.value])); }
        for (const [k, v] of Object.entries(flat)) { await api.putKv(prefix + k, label || undefined, { value: String(v), content_type: contentType || undefined }); n++; }
        notify.success(`Imported ${n} key-value${n === 1 ? "" : "s"} into '${store}'.`, "Import succeeded");
      } else {
        const items = (await api.listKv(filterLabel || undefined)).filter((i) => i.key.startsWith(filterPrefix) && !api.isFeatureFlag(i));
        const flat = Object.fromEntries(items.map((i) => [i.key.slice(filterPrefix.length), i.value ?? ""]));
        n = items.length;
        if (source === "file") { download(`${store}.${format === "properties" ? "properties" : format === "yaml" ? "yaml" : "json"}`, serialise(flat, format, sep || ".")); }
        else if (source === "appservice") { const a = appOf(app); if (!a) throw new Error("Choose an app."); await webApi.updateAppSettings(a.rg, a.name, { ...(await webApi.getAppSettings(a.rg, a.name)), ...Object.fromEntries(Object.entries(flat).map(([k, v]) => [k.replace(/[^A-Za-z0-9_.-]/g, "_"), v])) }); }
        else { if (!other) throw new Error("Choose a configuration store."); for (const i of items) await api.dpFor(other, "PUT", `/kv/${encodeURIComponent(i.key)}`, { query: i.label ? { label: i.label } : {}, body: { value: i.value, content_type: i.content_type || undefined } }); }
        notify.success(`Exported ${n} key-value${n === 1 ? "" : "s"}.`, "Export succeeded");
      }
      setResult(`${mode === "import" ? "Imported" : "Exported"} ${n} key-value${n === 1 ? "" : "s"}.`);
    } catch (e) { notify.error(e, `${mode === "import" ? "Import" : "Export"} failed`); }
    finally { setBusy(false); }
  };

  const isFile = source === "file";
  return (
    <>
      <div className="vy-panel-title">{store} | Import/export</div>
      <CapabilityContainer id={CAP} title="Import/export">
        <RadioGroup layout="horizontal" value={mode} onChange={(_, d) => { setMode(d.value); setResult(null); }} aria-label="Operation"><Radio value="import" label="Import" /><Radio value="export" label="Export" /></RadioGroup>
        <Field label={mode === "import" ? "Source service" : "Target service"}>
          <Select value={source} onChange={(_, d) => setSource(d.value)} aria-label="Service">
            <option value="file">Configuration file</option><option value="appservice">App Service</option><option value="store">Configuration store</option>
          </Select>
        </Field>
        {isFile && (
          <>
            {mode === "import" && <Field label="File" required><input type="file" accept=".json,.properties,.yaml,.yml" aria-label="File" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>}
            {mode === "export" && <Field label="File type"><Select value={format} onChange={(_, d) => setFormat(d.value)} aria-label="File type"><option value="json">JSON</option><option value="properties">Properties</option><option value="yaml">YAML</option></Select></Field>}
            <Field label="Separator"><Select value={sep} onChange={(_, d) => setSep(d.value)} aria-label="Separator">{[".", ":", "/", "-", "_"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
            {mode === "import" && <Field label="Depth (0 = all levels)"><Input type="number" value={depth} onChange={(_, d) => setDepth(d.value)} aria-label="Depth" /></Field>}
          </>)}
        {source === "appservice" && (apps.loading ? <Loading /> : <Field label="App"><Select value={app} onChange={(_, d) => setApp(d.value)} aria-label="App"><option value="">Select...</option>{(apps.data || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>)}
        {source === "store" && <Field label="Configuration store"><Select value={other} onChange={(_, d) => setOther(d.value)} aria-label="Configuration store"><option value="">Select...</option>{(stores.data || []).map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}</Select></Field>}
        {mode === "import" ? (
          <>
            <Field label="Prefix"><Input value={prefix} onChange={(_, d) => setPrefix(d.value)} aria-label="Prefix" /></Field>
            <Field label="Label"><Input value={label} onChange={(_, d) => setLabel(d.value)} aria-label="Label" /></Field>
            <Field label="Content type"><Input value={contentType} onChange={(_, d) => setContentType(d.value)} aria-label="Content type" /></Field>
          </>
        ) : (
          <>
            <Field label="From label"><Input value={filterLabel} onChange={(_, d) => setFilterLabel(d.value)} aria-label="From label" /></Field>
            <Field label="Key prefix to export (stripped)"><Input value={filterPrefix} onChange={(_, d) => setFilterPrefix(d.value)} aria-label="Key prefix" /></Field>
          </>)}
        <div style={{ marginTop: 12 }}><Button appearance="primary" disabled={busy} onClick={run}>{busy ? "Working..." : mode === "import" ? "Apply" : "Export"}</Button></div>
        {result && <InfoBar intent="success">{result}</InfoBar>}
      </CapabilityContainer>
    </>
  );
}
