/* Function detail: Code + Test (a real sandboxed run), Integration, Invocations, Logs, Metrics. */
import { useEffect, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, Link, Select, Table,
  TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowUpload20Regular, Delete20Regular, Dismiss20Regular, Link20Regular, PlayRegular, Save20Regular, SubtractCircle20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Glyph, InfoBar, Loading, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const TABS = [["code", "Code + Test"], ["integration", "Integration"], ["invocations", "Invocations"], ["logs", "Logs"], ["metrics", "Metrics"]];

export default function FunctionDetail({ params }) {
  const { rg, name, fn } = params;
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getFunction(rg, name, fn), [rg, name, fn]);
  const self = `#/functionapp/${encodeURIComponent(rg)}/${encodeURIComponent(name)}/functions/${encodeURIComponent(fn)}`;
  const [tab, setTab] = useState("code");
  const [del, setDel] = useState(false);
  const [url, setUrl] = useState(false);

  let body;
  if (loading && !data) body = <Loading />;
  else if (error) body = <><ErrorBar error={error} title="Failed to load the function" /><Link href={`#/functionapp/${rg}/${name}`}>Back to {name}</Link></>;
  else body = <CodeTest fn={data} rg={rg} name={name} fnName={fn} reload={reload} />;

  return (
    <ResourceBlade title={fn} subtitle="Function" glyph={<Glyph id="functionapp" />} closeHref={`#/functionapp/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`}
      menu={TABS.map(([id, label]) => ({ id, label }))} active={tab} hrefFor={() => self}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Function commands">
        <ToolbarButton icon={<Save20Regular />} onClick={reload}>Save</ToolbarButton>
        <ToolbarButton icon={<Dismiss20Regular />} onClick={reload}>Discard</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton icon={<PlayRegular />} onClick={() => setTab("code")}>Test/Run</ToolbarButton>
        <ToolbarButton icon={<ArrowUpload20Regular />} as="label">Upload<input type="file" hidden accept=".py" onChange={async (e) => {
          const file = e.target.files?.[0]; if (!file) return;
          const code = await file.text();
          try { await api.createFunction(rg, name, fn, { properties: { entryPoint: data?.properties?.entryPoint || "main", files: { "__init__.py": code }, config: data?.properties?.config } }); notify.success(`Uploaded ${file.name}.`, "Upload succeeded"); reload(); }
          catch (err) { notify.error(err, "Upload failed"); }
        }} /></ToolbarButton>
        <ToolbarButton icon={<Link20Regular />} onClick={() => setUrl(true)}>Get function URL</ToolbarButton>
        <ToolbarButton icon={<SubtractCircle20Regular />} onClick={async () => {
          try { await api.createFunction(rg, name, fn, { properties: { config: data?.properties?.config, isDisabled: !data?.properties?.isDisabled } }); reload(); }
          catch (e) { notify.error(e, "Failed"); }
        }}>{data?.properties?.isDisabled ? "Enable" : "Disable"}</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Function tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id}>{label}</Tab>)}
      </TabList>
      {tab === "code" && body}
      {tab === "integration" && <NotSimulatedContainer feature="Function input/output bindings editor (Integration)" />}
      {tab === "invocations" && <NotSimulatedContainer feature="The invocation history list (Invocations)" />}
      {tab === "logs" && <NotSimulatedContainer feature="Live log streaming for a single function (Logs)" />}
      {tab === "metrics" && <NotSimulatedContainer feature="Per-function metrics charts (Metrics)" />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="function" names={[fn]}
        onConfirm={async () => { await api.deleteFunction(rg, name, fn); notify.success(`Function '${fn}' was deleted.`, "Delete succeeded"); navigate("functionapp", rg, name); }} />
      <Dialog open={url} onOpenChange={(_, d) => setUrl(d.open)}>
        <DialogSurface aria-label="Function URL"><DialogBody><DialogTitle>Function URL</DialogTitle>
          <DialogContent><Input readOnly value={`https://${name}.azurewebsites.net/api/${fn}`} style={{ width: "100%" }} /></DialogContent>
          <DialogActions><Button onClick={() => setUrl(false)}>Close</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </ResourceBlade>
  );
}

function Row({ value, onChange, onRemove }) {
  return (
    <TableRow>
      <TableCell><Input size="small" value={value.name} onChange={(_, d) => onChange({ ...value, name: d.value })} aria-label="Name" /></TableCell>
      <TableCell><Input size="small" value={value.value} onChange={(_, d) => onChange({ ...value, value: d.value })} aria-label="Value" /></TableCell>
      <TableCell><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Remove" onClick={onRemove} /></TableCell>
    </TableRow>
  );
}

function KVTable({ label, rows, setRows }) {
  return (
    <div>
      <div style={{ fontWeight: 600, fontSize: 13, marginTop: 10 }}>{label}</div>
      <Table size="small" aria-label={label}>
        <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell style={{ width: 40 }} /></TableRow></TableHeader>
        <TableBody>
          {rows.map((r, i) => <Row key={i} value={r} onChange={(v) => setRows(rows.map((x, j) => (j === i ? v : x)))} onRemove={() => setRows(rows.filter((_, j) => j !== i))} />)}
        </TableBody>
      </Table>
      <Link as="button" onClick={() => setRows([...rows, { name: "", value: "" }])}>+ Add</Link>
    </div>
  );
}

function CodeTest({ fn, rg, name, fnName, reload }) {
  const notify = useNotify();
  const [code, setCode] = useState(fn?.properties?.files?.["__init__.py"] || api.DEFAULT_CODE);
  const [method, setMethod] = useState("GET");
  const [key, setKey] = useState("default");
  const [query, setQuery] = useState([]);
  const [headers, setHeaders] = useState([]);
  const [bodyText, setBodyText] = useState("{}");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setCode(fn?.properties?.files?.["__init__.py"] || api.DEFAULT_CODE); }, [fn]);

  const run = async () => {
    setBusy(true); setResult(null);
    try {
      let body; try { body = bodyText ? JSON.parse(bodyText) : {}; } catch { body = bodyText; }
      const req = { method, query: Object.fromEntries(query.filter((q) => q.name).map((q) => [q.name, q.value])),
                   headers: Object.fromEntries(headers.filter((h) => h.name).map((h) => [h.name, h.value])), body };
      const r = await api.invokeFunction(rg, name, fnName, req);
      setResult(r);
    } catch (e) { notify.error(e, "Run failed"); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ display: "flex", gap: 24, marginTop: 12, flexWrap: "wrap" }}>
      <div style={{ flex: "2 1 420px", minWidth: 320 }}>
        <div className="vy-panel-title">__init__.py</div>
        <Textarea value={code} onChange={(_, d) => setCode(d.value)} rows={16} style={{ width: "100%", fontFamily: "monospace" }} aria-label="Function code" />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Button appearance="primary" onClick={async () => {
            try { await api.createFunction(rg, name, fnName, { properties: { entryPoint: fn?.properties?.entryPoint || "main", files: { "__init__.py": code }, config: fn?.properties?.config } }); notify.success("Saved.", "Code saved"); reload(); }
            catch (e) { notify.error(e, "Save failed"); }
          }}>Save</Button>
          <Button onClick={() => setCode(fn?.properties?.files?.["__init__.py"] || api.DEFAULT_CODE)}>Discard</Button>
        </div>
      </div>
      <div style={{ flex: "1 1 320px", minWidth: 300, borderLeft: "1px solid var(--colorNeutralStroke2)", paddingLeft: 20 }}>
        <div className="vy-panel-title">Test</div>
        <InfoBar>Run executes the real function code in a restricted sandbox (no filesystem/network access).</InfoBar>
        <div className="vy-form-row"><label htmlFor="ft-method">HTTP method</label>
          <Select id="ft-method" value={method} onChange={(_, d) => setMethod(d.value)} aria-label="HTTP method">
            <option value="GET">GET</option><option value="POST">POST</option><option value="PUT">PUT</option><option value="DELETE">DELETE</option><option value="PATCH">PATCH</option>
          </Select>
        </div>
        <div className="vy-form-row"><label htmlFor="ft-key">Key</label>
          <Select id="ft-key" value={key} onChange={(_, d) => setKey(d.value)} aria-label="Key"><option value="default">default</option></Select>
        </div>
        <KVTable label="Query" rows={query} setRows={setQuery} />
        <KVTable label="Headers" rows={headers} setRows={setHeaders} />
        <div className="vy-form-row"><label htmlFor="ft-body">Body</label>
          <Textarea id="ft-body" value={bodyText} onChange={(_, d) => setBodyText(d.value)} rows={4} style={{ width: "100%", fontFamily: "monospace" }} aria-label="Body" />
        </div>
        <Button appearance="primary" style={{ marginTop: 8 }} disabled={busy} onClick={run}>{busy ? "Running..." : "Run"}</Button>
        {result && (
          <pre className="vy-mono" style={{ marginTop: 12, maxHeight: 220, overflow: "auto", background: "var(--colorNeutralBackground3)", padding: 10, borderRadius: 4, fontSize: 12 }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
