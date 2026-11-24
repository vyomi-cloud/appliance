/* Deploy a custom template into a resource group (the portal's "Deploy a custom template" flow, opened from
 * Deployments > Deploy template). ARM JSON (and Bicep compiled to JSON) deploys through
 *   POST .../deployments/{name}/whatIf   and   PUT .../deployments/{name}
 * against the simulator's ARM core, which really creates what the template declares (core/azure_deploy_core.py).
 * "Import Terraform (azurerm)" is a Vyomi extra on top: the dropped .tf is converted to an ARM template by
 *   POST .../resourceGroups/{rg}/importTerraform
 * (azurerm_* blocks plus azapi_resource), unsupported blocks are listed explicitly, then the same deploy path runs. */
import { useRef, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, MessageBar, MessageBarBody, Select, Tab, TabList, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { restJson } from "../../../common/wire.js";
import { getSubscription } from "../../kit/arm.js";

const AV = "2022-09-01";
const base = (rg) => `/subscriptions/${getSubscription()}/resourceGroups/${encodeURIComponent(rg)}`;
const dpath = (rg, name, tail = "") => `${base(rg)}/providers/Microsoft.Resources/deployments/${encodeURIComponent(name)}${tail}`;
const CHANGE_LABEL = { Create: "Create", Modify: "Modify", Delete: "Delete", NoChange: "No change", Ignore: "Ignore", Deploy: "Deploy" };
const CHANGE_GLYPH = { Create: "+", Modify: "~", Delete: "-", NoChange: "=", Ignore: "=", Deploy: "*" };

function paramDefaults(tpl) {
  const out = {};
  for (const [k, p] of Object.entries(tpl?.parameters || {})) out[k] = p.defaultValue === undefined ? "" : (typeof p.defaultValue === "string" ? p.defaultValue : JSON.stringify(p.defaultValue));
  return out;
}
function coerce(def, raw) {
  const t = String(def?.type || "string").toLowerCase();
  if (t === "int") return Number(raw);
  if (t === "bool") return raw === true || String(raw).toLowerCase() === "true";
  if (t === "array" || t === "object" || t === "secureobject") { try { return JSON.parse(raw); } catch { return raw; } }
  return raw;
}

export default function DeployTemplate({ rg, open, onClose, onDeployed }) {
  const notify = useNotify();
  const [tab, setTab] = useState("arm");
  const [text, setText] = useState("");
  const [tpl, setTpl] = useState(null);
  const [report, setReport] = useState(null);
  const [vals, setVals] = useState({});
  const [name, setName] = useState(`deployment-${new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "")}`);
  const [mode, setMode] = useState("Incremental");
  const [whatif, setWhatif] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  const reset = () => { setTpl(null); setReport(null); setWhatif(null); setError(null); };
  const readFile = async (f) => {
    if (!f) return;
    const body = await f.text();
    reset();
    if (/\.bicep$/i.test(f.name)) { setError("Bicep files must be compiled to an ARM JSON template first (az bicep build); the simulator deploys ARM JSON."); return; }
    setTab(/\.tf$/i.test(f.name) ? "tf" : "arm");
    setText(body);
  };
  const load = async () => {
    reset(); setBusy(true);
    try {
      if (tab === "arm") {
        const t = JSON.parse(text);
        if (!Array.isArray(t.resources) && !t.outputs) throw new Error("The template has no 'resources' array.");
        setTpl(t); setVals(paramDefaults(t));
      } else {
        const r = await restJson("POST", `${base(rg)}/importTerraform`, { query: { "api-version": AV }, body: { terraform: text } });
        setReport(r);
        if (r.template) { setTpl(r.template); setVals(paramDefaults(r.template)); }
      }
    } catch (e) { setError(e?.message || String(e)); } finally { setBusy(false); }
  };
  const body = () => ({
    properties: {
      mode, template: tpl,
      parameters: Object.fromEntries(Object.entries(tpl?.parameters || {}).filter(([k]) => vals[k] !== "" && vals[k] !== undefined).map(([k, d]) => [k, { value: coerce(d, vals[k]) }])),
    },
  });
  const missing = Object.entries(tpl?.parameters || {}).filter(([k, d]) => d.defaultValue === undefined && (vals[k] === "" || vals[k] === undefined)).map(([k]) => k);
  const runWhatIf = async () => {
    setBusy(true); setWhatif(null); setError(null);
    try { setWhatif(await restJson("POST", dpath(rg, name, "/whatIf"), { query: { "api-version": AV }, body: body() })); }
    catch (e) { setError(e?.message || String(e)); } finally { setBusy(false); }
  };
  const deploy = async () => {
    setBusy(true); setError(null);
    try {
      const r = await restJson("PUT", dpath(rg, name), { query: { "api-version": AV }, body: body() });
      const st = r?.properties?.provisioningState;
      if (st === "Failed") {
        const det = (r.properties.error?.details || []).map((d) => `${d.resource || d.code}: ${d.error?.error?.message || d.error?.message || d.message || ""}`).join("; ");
        setError(`Deployment '${name}' failed. ${det}`);
      } else {
        notify.success(`Deployment '${name}' succeeded (${(r.properties.outputResources || []).length} resources).`, "Deployment succeeded");
        onDeployed?.(); onClose();
      }
    } catch (e) { setError(e?.message || String(e)); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Deploy a custom template" style={{ maxWidth: 860, width: "92vw" }}>
        <DialogBody>
          <DialogTitle>Custom deployment</DialogTitle>
          <DialogContent>
            <p className="vy-muted" style={{ marginTop: 0 }}>Deploy an ARM template (JSON, or Bicep compiled to JSON) to <b>{rg}</b>. Vyomi extra: import a Terraform (azurerm) configuration.</p>
            <TabList selectedValue={tab} onTabSelect={(_, d) => { setTab(d.value); reset(); }} aria-label="Template source">
              <Tab value="arm">Build your own template (ARM JSON)</Tab>
              <Tab value="tf">Import Terraform (azurerm)</Tab>
            </TabList>
            <div
              style={{ border: "1px dashed var(--colorNeutralStroke1, #888)", borderRadius: 4, padding: 8, margin: "8px 0" }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); readFile(e.dataTransfer.files?.[0]); }}
              data-testid="deploy-dropzone">
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                <Button size="small" onClick={() => fileRef.current?.click()}>{tab === "arm" ? "Upload template.json" : "Upload .tf file"}</Button>
                <span className="vy-muted">or drop a {tab === "arm" ? ".json" : ".tf"} file here, or paste below</span>
                <input ref={fileRef} type="file" accept={tab === "arm" ? ".json,.bicep" : ".tf"} data-testid="deploy-file" style={{ display: "none" }} onChange={(e) => readFile(e.target.files?.[0])} />
              </div>
              <Textarea aria-label={tab === "arm" ? "ARM template JSON" : "Terraform configuration"} data-testid="deploy-text" value={text}
                onChange={(_, d) => { setText(d.value); reset(); }} style={{ width: "100%" }} textarea={{ style: { minHeight: 170, fontFamily: "monospace", fontSize: 12 } }} resize="vertical" />
            </div>
            <Button appearance="primary" disabled={busy || !text.trim()} onClick={load} data-testid="deploy-load">{tab === "arm" ? "Load template" : "Convert to ARM template"}</Button>
            {error && <MessageBar intent="error" style={{ marginTop: 8 }} data-testid="deploy-error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
            {report && (
              <div style={{ marginTop: 8 }} data-testid="tf-report">
                <MessageBar intent={report.unsupported?.length ? "warning" : "success"}>
                  <MessageBarBody>Converted {report.mapped?.length || 0} Terraform resource(s) to an ARM template{report.unsupported?.length ? `; ${report.unsupported.length} block(s) are not supported and were NOT converted:` : "."}</MessageBarBody>
                </MessageBar>
                {report.unsupported?.length > 0 && <ul data-testid="tf-unsupported">{report.unsupported.map((u) => <li key={u.address}><code>{u.address}</code> - {u.reason}</li>)}</ul>}
                {report.warnings?.length > 0 && <ul>{report.warnings.map((w, i) => <li key={i} className="vy-muted">{w}</li>)}</ul>}
              </div>
            )}
            {tpl && (
              <div style={{ marginTop: 12 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <Field label="Deployment name"><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Deployment name" /></Field>
                  <Field label="Deployment mode"><Select value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Deployment mode"><option>Incremental</option><option>Complete</option></Select></Field>
                </div>
                {Object.keys(tpl.parameters || {}).length > 0 && (
                  <>
                    <p style={{ fontWeight: 600, margin: "10px 0 4px" }}>Parameters</p>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }} data-testid="deploy-params">
                      {Object.entries(tpl.parameters).map(([k, d]) => (
                        <Field key={k} label={`${k}${d.defaultValue === undefined ? " *" : ""}`} hint={d.metadata?.description}>
                          <Input type={/secure/i.test(d.type || "") ? "password" : "text"} value={vals[k] ?? ""} aria-label={`Parameter ${k}`} onChange={(_, v) => setVals({ ...vals, [k]: v.value })} />
                        </Field>
                      ))}
                    </div>
                  </>
                )}
                <p className="vy-muted" style={{ marginTop: 8 }}>{(tpl.resources || []).length} resource(s) in the template.</p>
                {whatif && (
                  <div data-testid="whatif-result" style={{ marginTop: 8 }}>
                    <p style={{ fontWeight: 600, margin: "4px 0" }}>What-if</p>
                    {whatif.error ? <MessageBar intent="error"><MessageBarBody>{whatif.error.message}</MessageBarBody></MessageBar> : (
                      <table className="vy-grid" aria-label="What-if changes">
                        <thead><tr><th /><th>Change</th><th>Resource</th><th>Detail</th></tr></thead>
                        <tbody>
                          {(whatif.properties?.changes || []).map((c) => (
                            <tr key={c.resourceId} data-change={c.changeType}>
                              <td><code>{CHANGE_GLYPH[c.changeType] || "?"}</code></td><td>{CHANGE_LABEL[c.changeType] || c.changeType}</td>
                              <td style={{ wordBreak: "break-all" }}>{c.resourceId.split("/providers/").pop()}</td>
                              <td className="vy-muted">{(c.delta || []).map((d) => d.path).slice(0, 4).join(", ")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            )}
          </DialogContent>
          <DialogActions>
            <Button disabled={!tpl || busy || missing.length > 0} onClick={runWhatIf} data-testid="deploy-whatif" title={missing.length ? `Missing: ${missing.join(", ")}` : ""}>What-if</Button>
            <Button appearance="primary" disabled={!tpl || busy || missing.length > 0} onClick={deploy} data-testid="deploy-go" title={missing.length ? `Missing: ${missing.join(", ")}` : ""}>Review + create</Button>
            <Button onClick={onClose}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
