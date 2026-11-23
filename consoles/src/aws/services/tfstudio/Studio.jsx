/* Infrastructure Studio: the stack as a diagram, exported as Terraform, plus a check of which resource types of a template Vyomi can
 * create. Availability colours: available / planned / not possible in Vyomi. Read-only; applying a template is done with OpenTofu/Terraform
 * against this endpoint (in-browser apply is not available yet). */
import { useCallback, useEffect, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Diagram from "./Diagram.jsx";
import * as api from "./api.js";

const COL = { supported: "#1d8102", planned: "#b7791f", not_possible: "#d13212" };
const LABEL = { supported: "Available in Vyomi", planned: "Planned, not simulated yet", not_possible: "Not possible in Vyomi" };

function Legend() {
  return (
    <SpaceBetween direction="horizontal" size="l">
      {Object.keys(LABEL).map((k) => (
        <Box key={k} variant="small"><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 5, background: COL[k], marginRight: 6 }} />{LABEL[k]}</Box>
      ))}
    </SpaceBetween>
  );
}

const MODES = [{ value: "sim", label: "Target: Vyomi" }, { value: "real", label: "Target: real AWS" }];

function ExportTab() {
  const [mode, setMode] = useState(MODES[0]);
  const [graph, setGraph] = useState(null), [bundle, setBundle] = useState(null), [err, setErr] = useState(null);
  const [sel, setSel] = useState(null), [file, setFile] = useState(null);
  const load = useCallback(async () => {
    setErr(null);
    try {
      const [g, b] = await Promise.all([api.getGraph(), api.getBundle(mode.value)]);
      setGraph(g); setBundle(b); setSel(null);
      setFile((f) => (f && b.files[f] != null ? f : Object.keys(b.files).sort()[0] || null));
    } catch (e) { setErr(e); setGraph(null); setBundle(null); }
  }, [mode.value]);
  useEffect(() => { load(); }, [load]);

  const node = graph && sel ? graph.nodes.find((n) => n.id === sel) : null;
  const uses = node ? graph.edges.filter((e) => e.from === node.id).map((e) => e.to) : [];
  const usedBy = node ? graph.edges.filter((e) => e.to === node.id).map((e) => e.from) : [];
  const gaps = graph ? Object.entries(graph.availability).filter(([, v]) => v.status !== "supported") : [];
  const files = bundle ? Object.keys(bundle.files).sort() : [];

  return (
    <SpaceBetween size="l">
      {err && <Alert type="error" header="Could not read the stack">{String(err.message || err)} from {api.getBase() || "this page"}. The diagram and export read the Terraform API of the backend that holds your resources (a Vyomi appliance or your Mesh).</Alert>}
      <ColumnLayout columns={2}>
        <Select selectedOption={mode} onChange={({ detail }) => setMode(detail.selectedOption)} options={MODES} ariaLabel="Export target" />
        <SpaceBetween direction="horizontal" size="xs"><Button onClick={load} iconName="refresh">Refresh</Button></SpaceBetween>
      </ColumnLayout>
      <Container header={<Header variant="h2" description="Click a resource to see what it uses and what uses it.">Stack diagram</Header>}>
        <SpaceBetween size="m">
          <Legend />
          {graph && graph.nodes.length === 0 && <Box color="text-status-inactive">No resources in this space yet. Apply a Terraform template or create resources, then refresh.</Box>}
          {graph && graph.nodes.length > 0 && <Diagram graph={graph} selected={sel} onSelect={setSel} />}
          {!graph && !err && <Box color="text-status-inactive">Reading your stack...</Box>}
        </SpaceBetween>
      </Container>
      <ColumnLayout columns={3}>
        <Container header={<Header variant="h3">Selected</Header>}>
          {node ? (
            <SpaceBetween size="xs">
              <Box variant="strong">{node.id}</Box>
              <Box variant="small">Status: {LABEL[node.status]}{graph.availability[node.type]?.reason ? ` - ${graph.availability[node.type].reason}` : ""}</Box>
              <Box variant="small">Uses: {uses.join(", ") || "-"}</Box>
              <Box variant="small">Used by: {usedBy.join(", ") || "-"}</Box>
            </SpaceBetween>
          ) : <Box color="text-status-inactive">Choose a resource in the diagram.</Box>}
        </Container>
        <Container header={<Header variant="h3">Unavailable in Vyomi</Header>}>
          {gaps.length ? gaps.map(([t, v]) => <Box key={t} variant="small"><b>{t}</b> <span style={{ color: COL[v.status] }}>({v.status.replace("_", " ")})</span><br />{v.reason}</Box>) : <Box color="text-status-inactive">None.</Box>}
        </Container>
        <Container header={<Header variant="h3">Before you apply on real AWS</Header>}>
          {bundle ? (bundle.portability || []).map((p, i) => <Box key={i} variant="small"><b style={{ color: p.severity === "error" ? "#d13212" : p.severity === "warn" ? "#b7791f" : undefined }}>{p.severity}</b> {p.message}{p.resource ? <><br /><span style={{ color: "#5f6b7a" }}>{p.resource}</span></> : null}</Box>) : <Box color="text-status-inactive">-</Box>}
        </Container>
      </ColumnLayout>
      <Container header={<Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs">
        <Select selectedOption={file ? { value: file, label: file } : null} onChange={({ detail }) => setFile(detail.selectedOption.value)} options={files.map((f) => ({ value: f, label: f }))} placeholder="File" ariaLabel="Terraform file" />
        <Button variant="primary" iconName="download" href={api.zipUrl(mode.value)} disabled={!bundle}>Download .zip</Button></SpaceBetween>}>Terraform files</Header>}>
        <pre style={{ margin: 0, maxHeight: 360, overflow: "auto", fontSize: 12 }}>{(bundle && file && bundle.files[file]) || ""}</pre>
      </Container>
    </SpaceBetween>
  );
}

function ImportTab() {
  const [rows, setRows] = useState(null), [err, setErr] = useState(null), [none, setNone] = useState(false);
  const onFiles = async (files) => {
    setErr(null); setNone(false); setRows(null);
    const types = new Set();
    for (const f of files) { const t = await f.text(); for (const m of t.matchAll(/^\s*resource\s+"([a-z0-9_]+)"/gm)) types.add(m[1]); }
    if (!types.size) { setNone(true); return; }
    try { const r = await api.classify([...types]); setRows(Object.entries(r.availability).map(([type, v]) => ({ type, ...v }))); } catch (e) { setErr(e); }
  };
  const ok = rows ? rows.filter((r) => r.status === "supported").length : 0;
  return (
    <Container header={<Header variant="h2" description="Lists which resource types in your template Vyomi can create. Apply the template with OpenTofu or Terraform against this endpoint; applying inside the browser is not available yet.">Check a Terraform template</Header>}>
      <SpaceBetween size="m">
        <input type="file" accept=".tf" multiple onChange={(e) => onFiles([...e.target.files])} aria-label="Terraform files" />
        {none && <Alert type="warning">No resource blocks found.</Alert>}
        {err && <Alert type="error">Could not check the template: {String(err.message || err)}</Alert>}
        {rows && (<>
          <Box>{ok} of {rows.length} resource types can be created in Vyomi.</Box>
          <Table items={rows} variant="embedded" columnDefinitions={[
            { id: "type", header: "Resource type", cell: (r) => r.type },
            { id: "status", header: "In Vyomi", cell: (r) => <span style={{ color: COL[r.status] }}>{LABEL[r.status]}</span> },
            { id: "why", header: "Reason", cell: (r) => r.reason || "-" }]} />
        </>)}
      </SpaceBetween>
    </Container>
  );
}

export default function Studio() {
  const [base, setBase] = useState(api.getBase());
  const [key, setKey] = useState(0);
  return (
    <ContentLayout header={<Header variant="h1" description="See your AWS stack as a diagram, export it as Terraform, or check a Terraform template before you apply it."
      actions={<SpaceBetween direction="horizontal" size="xs"><Box variant="small" padding={{ top: "xs" }}>Backend</Box>
        <Input value={base} placeholder="this page" onChange={({ detail }) => setBase(detail.value)} onBlur={() => { api.setBase(base); setKey((k) => k + 1); }} /></SpaceBetween>}>Infrastructure Studio</Header>}>
      <Tabs key={key} tabs={[{ id: "export", label: "Export", content: <ExportTab /> }, { id: "import", label: "Import", content: <ImportTab /> }]} />
    </ContentLayout>
  );
}
