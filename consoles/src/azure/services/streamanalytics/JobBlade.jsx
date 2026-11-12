/* Stream Analytics job blade: Overview (start/stop + last run), Inputs, Outputs, Query (test + save), Results.
 * Backed by core/azure_streamanalytics_core.py; the runner executes a batch over Blob inputs (see capability JSON). */
import { useState } from "react";
import { Button, Field, Input, Link, Select, Textarea, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular, Delete20Regular, Play20Regular, Stop20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, InfoBar, Loading, NotSimulatedContainer } from "../../kit/common.jsx";
import SharedActivityLog from "../../kit/ActivityLog.jsx";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { group: "Job topology", items: [{ id: "inputs", label: "Inputs" }, { id: "outputs", label: "Outputs" }, { id: "query", label: "Query" }, { id: "results", label: "Results" }] },
  { group: "Support + troubleshooting", items: [{ id: "diagnose", label: "Diagnose and solve problems" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

export default function JobBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const job = useAsync(() => api.getJob(rg, name), [rg, name]);
  const self = `#/streamanalytics/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  let body;
  if (job.loading && !job.data) body = <Loading />;
  else if (job.error) body = <><ErrorBar error={job.error} title="Failed to load the Stream Analytics job" /><Link href="#/streamanalytics">Back to jobs</Link></>;
  else {
    const j = job.data, reload = job.reload;
    const P = {
      overview: () => <Overview j={j} rg={rg} reload={reload} />,
      inputs: () => <Children kind="inputs" j={j} rg={rg} reload={reload} />,
      outputs: () => <Children kind="outputs" j={j} rg={rg} reload={reload} />,
      query: () => <Query j={j} rg={rg} reload={reload} />,
      results: () => <Results j={j} />,
      activitylog: () => <SharedActivityLog scope={j.id} name={j.name} />,
      diagnose: () => <NotSimulatedContainer title={`${j.name} | Diagnose and solve problems`} feature="Stream Analytics diagnostics" />,
    }[panel];
    body = P ? <CapabilityContainer id="azure.streamanalytics.jobs" title={`${j.name} | ${LABEL[panel]}`}>{P()}</CapabilityContainer> : null;
  }
  return (
    <ResourceBlade title={name} subtitle="Stream Analytics job" glyph={<Glyph id="eventgrid" />} closeHref="#/streamanalytics"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}>
      {body}
    </ResourceBlade>
  );
}

function Overview({ j, rg, reload }) {
  const notify = useNotify();
  const [err, setErr] = useState(null);
  const p = j.properties || {};
  const act = async (fn, ok) => { setErr(null); try { await fn(); notify.success(ok, "Succeeded"); } catch (e) { setErr(e); } reload(); };
  const run = p.vyomiRun;
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Play20Regular />} onClick={() => act(() => api.startJob(rg, j.name), "Job started.")}>Start</ToolbarButton>
        <ToolbarButton icon={<Stop20Regular />} onClick={() => act(() => api.stopJob(rg, j.name), "Job stopped.")}>Stop</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={async () => { try { await api.deleteJob(rg, j.name); navigate("streamanalytics"); } catch (e) { setErr(e); } }}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <ErrorBar error={err} title="Operation failed" />
      {p.vyomiError && <InfoBar intent="error" title={p.vyomiError.code}>{p.vyomiError.message}</InfoBar>}
      <Essentials
        left={[["Resource group", rg], ["Location", j.location], ["Status", <span data-testid="job-state">{p.jobState}</span>], ["Compatibility level", p.compatibilityLevel]]}
        right={[["Inputs", (p.inputs || []).length], ["Outputs", (p.outputs || []).length], ["Streaming units", p.transformation?.properties?.streamingUnits ?? "--"], ["Output start mode", p.outputStartMode]]}
      />
      {run && (
        <div data-testid="run-summary" style={{ marginTop: 16 }}>
          <h3>Last run</h3>
          <p>{run.inputFiles} input blob(s), {run.inputEvents} input event(s), {run.outputEvents} output event(s) at {run.ranAt}.</p>
          <p>Output: <code>{run.outputBlob}</code></p>
        </div>
      )}
    </>
  );
}

const BLOB_DEFAULT = { account: "", container: "", path: "", format: "LineSeparated", type: "Json" };
function Children({ kind, j, rg, reload }) {
  const notify = useNotify();
  const items = j.properties?.[kind] || [];
  const [f, setF] = useState({ name: "", dsType: "Microsoft.Storage/Blob", ...BLOB_DEFAULT, ns: "", hub: "" });
  const [err, setErr] = useState(null);
  const [testRes, setTestRes] = useState({});
  const isIn = kind === "inputs";
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const add = async () => {
    setErr(null);
    const blob = f.dsType === "Microsoft.Storage/Blob";
    const datasource = blob
      ? { type: f.dsType, properties: { storageAccounts: [{ accountName: f.account }], container: f.container, ...(f.path ? { pathPattern: f.path } : {}) } }
      : { type: f.dsType, properties: { serviceBusNamespace: f.ns, eventHubName: f.hub } };
    const serialization = { type: f.type, properties: f.type === "Json" ? { encoding: "UTF8", format: f.format } : { encoding: "UTF8", fieldDelimiter: "," } };
    try {
      await api.putChild(rg, j.name, kind, f.name, { properties: { ...(isIn ? { type: "Stream" } : {}), datasource, serialization } });
      notify.success(`${isIn ? "Input" : "Output"} ${f.name} saved.`, "Succeeded");
      setF({ ...f, name: "" }); reload();
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <table className="vy-table" aria-label={kind} style={{ width: "100%", marginBottom: 16 }}>
        <thead><tr><th align="left">Alias</th><th align="left">Source type</th><th align="left">Details</th><th align="left">Test</th><th /></tr></thead>
        <tbody>
          {items.map((c) => {
            const ds = c.properties.datasource, pr = ds.properties || {};
            return (
              <tr key={c.name}>
                <td>{c.name}</td><td>{ds.type}</td>
                <td>{pr.container ? `${pr.storageAccounts?.[0]?.accountName}/${pr.container}` : `${pr.serviceBusNamespace}/${pr.eventHubName}`}</td>
                <td>
                  <Button size="small" onClick={async () => setTestRes({ ...testRes, [c.name]: (await api.testChild(rg, j.name, kind, c.name)).status })}>Test</Button>{" "}
                  <span data-testid={`test-${c.name}`}>{testRes[c.name]}</span>
                </td>
                <td><Button size="small" onClick={async () => { try { await api.deleteChild(rg, j.name, kind, c.name); reload(); } catch (e) { setErr(e); } }}>Delete</Button></td>
              </tr>
            );
          })}
          {!items.length && <tr><td colSpan={5}>No {kind} defined.</td></tr>}
        </tbody>
      </table>
      <ErrorBar error={err} title="Save failed" />
      <h3>Add {isIn ? "stream input" : "output"}</h3>
      <div style={{ display: "grid", gap: 8, maxWidth: 480 }}>
        <Field label={isIn ? "Input alias" : "Output alias"}><Input aria-label="Alias" value={f.name} onChange={set("name")} /></Field>
        <Field label="Source type"><Select aria-label="Source type" value={f.dsType} onChange={set("dsType")}>
          <option value="Microsoft.Storage/Blob">Blob storage</option><option value="Microsoft.EventHub/EventHub">Event Hub</option>
        </Select></Field>
        {f.dsType === "Microsoft.Storage/Blob" ? <>
          <Field label="Storage account"><Input aria-label="Storage account" value={f.account} onChange={set("account")} /></Field>
          <Field label="Container"><Input aria-label="Container" value={f.container} onChange={set("container")} /></Field>
          <Field label="Path pattern (optional)"><Input aria-label="Path pattern" value={f.path} onChange={set("path")} /></Field>
        </> : <>
          <Field label="Event Hub namespace"><Input aria-label="Event Hub namespace" value={f.ns} onChange={set("ns")} /></Field>
          <Field label="Event Hub name"><Input aria-label="Event Hub name" value={f.hub} onChange={set("hub")} /></Field>
        </>}
        <Field label="Serialization format"><Select aria-label="Serialization format" value={f.type} onChange={set("type")}><option>Json</option><option>Csv</option><option>Avro</option></Select></Field>
        <Button appearance="primary" onClick={add}>Save</Button>
      </div>
    </>
  );
}

function Query({ j, rg, reload }) {
  const notify = useNotify();
  const cur = j.properties?.transformation?.properties?.query || "SELECT *\nINTO [YourOutputAlias]\nFROM [YourInputAlias]";
  const [q, setQ] = useState(cur);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Query commands">
        <ToolbarButton onClick={async () => { setErr(null); try { setRes(await api.testQuery(rg, j.name, q)); } catch (e) { setErr(e); } }}>Test query</ToolbarButton>
        <ToolbarButton onClick={async () => { setErr(null); try { await api.putQuery(rg, j.name, q); notify.success("Query saved.", "Succeeded"); reload(); } catch (e) { setErr(e); } }}>Save query</ToolbarButton>
      </div>
      <ErrorBar error={err} title="Query error" />
      <Textarea aria-label="Query editor" value={q} onChange={(_, d) => setQ(d.value)} rows={12} style={{ width: "100%", fontFamily: "monospace" }} />
      {res && <div data-testid="query-test"><InfoBar intent={res.status === "TestSucceeded" ? "success" : "error"} title={res.status}>{res.error?.message || "The query is valid for this job."}</InfoBar></div>}
    </>
  );
}

function Results({ j }) {
  const url = j.properties?.vyomiRun?.outputBlob;
  const rows = useAsync(() => api.readOutput(url), [url]);
  if (!url) return <InfoBar>Start the job to produce output. Results come from the Blob output the job wrote.</InfoBar>;
  const data = rows.data || [];
  const cols = [...new Set(data.flatMap((r) => Object.keys(r)))];
  return (
    <>
      <p>Output blob: <code>{url}</code></p>
      <ErrorBar error={rows.error} />
      <table className="vy-table" aria-label="Results" style={{ width: "100%" }}>
        <thead><tr>{cols.map((c) => <th key={c} align="left">{c}</th>)}</tr></thead>
        <tbody>{data.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c])}</td>)}</tr>)}</tbody>
      </table>
    </>
  );
}
