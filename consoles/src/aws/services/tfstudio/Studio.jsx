/* Infrastructure Studio: the stack as a diagram, exported as Terraform, and imported again: a Terraform bundle is planned, applied
 * through Vyomi's own AWS API (appliance, Mesh or Nano) and can be destroyed. Availability: available / planned / not possible in Vyomi. */
import { useCallback, useEffect, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import FileUpload from "@cloudscape-design/components/file-upload";
import FormField from "@cloudscape-design/components/form-field";
import Modal from "@cloudscape-design/components/modal";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Textarea from "@cloudscape-design/components/textarea";
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
      <ColumnLayout columns={2}>
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
      </ColumnLayout>
      <Container header={<Header variant="h2" description="Notes from the exporter about moving this stack to a real AWS account.">Before you apply on real AWS</Header>}>
        {bundle ? (() => { const all = bundle.portability || [], warns = all.filter((p) => p.severity !== "info"), infos = all.filter((p) => p.severity === "info");
          const item = (p, i) => <li key={i} style={{ marginBottom: 6 }}><b>{p.message}</b>{p.resource ? <><br /><span style={{ color: "#5f6b7a" }}>{p.resource}</span></> : null}</li>;
          const list = (a) => a.length ? <ul style={{ margin: 0, paddingLeft: 20 }}>{a.map(item)}</ul> : "None.";
          return <ColumnLayout columns={2}>
            <Alert type={warns.some((p) => p.severity === "error") ? "error" : "warning"} header={`Warnings (${warns.length})`}>{list(warns)}</Alert>
            <Alert type="info" header={`Info (${infos.length})`}>{list(infos)}</Alert>
          </ColumnLayout>; })() : <Box color="text-status-inactive">-</Box>}
      </Container>
      <Container header={<Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs">
        <Select selectedOption={file ? { value: file, label: file } : null} onChange={({ detail }) => setFile(detail.selectedOption.value)} options={files.map((f) => ({ value: f, label: f }))} placeholder="File" ariaLabel="Terraform file" />
        <Button variant="primary" iconName="download" disabled={!bundle} onClick={() => api.downloadZip(mode.value)}>Download .zip</Button></SpaceBetween>}>Terraform files</Header>}>
        <pre style={{ margin: 0, maxHeight: 360, overflow: "auto", fontSize: 12 }}>{(bundle && file && bundle.files[file]) || ""}</pre>
      </Container>
    </SpaceBetween>
  );
}

const ACTION = { create: ["pending", "Will be created"], exists: ["success", "Already in Vyomi"], created: ["success", "Created"], pending: ["pending", "Waiting"], running: ["in-progress", "Creating"],
  unsupported: ["warning", "Cannot import yet"], blocked: ["stopped", "Blocked"], error: ["error", "Error"], failed: ["error", "Failed"], destroyed: ["stopped", "Destroyed"] };

const tally = (rows) => { const n = (...a) => rows.filter((r) => a.includes(r.action)).length;
  return [`${n("create", "running")} to create`, n("created") && `${n("created")} created`, `${n("exists")} already in Vyomi`, `${n("unsupported")} not importable`, `${n("blocked", "error", "failed", "pending")} blocked or in error`, n("destroyed") && `${n("destroyed")} destroyed`].filter(Boolean).join(", ") + "."; };

function Availability({ a }) {
  const st = (a && a.status) || "planned";
  return <StatusIndicator type={st === "supported" ? "success" : st === "planned" ? "warning" : "error"}>{{ supported: "Available", planned: "Planned", not_possible: "Not possible" }[st]}</StatusIndicator>;
}

/** Import: drop or paste Terraform (.tf / .tfvars / .zip), see what Vyomi would create, apply it through Vyomi's own AWS API, and tear it down again. */
function ImportTab({ onChanged, onShowDiagram }) {
  const [bundle, setBundle] = useState({ files: {}, binaries: {} }), [pasted, setPasted] = useState(""), [vars, setVars] = useState({});
  const [plan, setPlan] = useState(null), [rows, setRows] = useState([]), [err, setErr] = useState(null), [busy, setBusy] = useState(""), [prog, setProg] = useState(null);
  const [done, setDone] = useState(null), [confirm, setConfirm] = useState(false), [ledger, setLedger] = useState(api.getLedger());
  const [uploads, setUploads] = useState([]);
  const names = Object.keys(bundle.files).length + Object.keys(bundle.binaries).length;
  const payload = useCallback((b = bundle) => ({ ...b, files: pasted.trim() ? { ...b.files, "pasted.tf": pasted } : b.files, variables: vars }), [bundle, pasted, vars]);

  const runPlan = useCallback(async (b) => {
    const p = payload(b);
    if (!Object.keys(p.files).length) { setPlan(null); setRows([]); return; }
    setErr(null); setBusy("plan");
    try { const r = await api.planBundle(p); setPlan(r); setRows(r.items || []); } catch (e) { setErr(e); setPlan(null); setRows([]); } finally { setBusy(""); }
  }, [payload]);

  const onUpload = async (list) => {
    setUploads(list); setDone(null);
    try { const b = await api.readBundle(list, ""); setBundle(b); await runPlan(b); } catch (e) { setErr(e); }
  };
  useEffect(() => { const t = setTimeout(() => { if (pasted.trim() || names) runPlan(bundle); }, 600); return () => clearTimeout(t); /* eslint-disable-next-line */ }, [pasted, vars]);

  const sum = plan ? plan.summary : null;
  const toCreate = rows.filter((r) => r.action === "create");
  const missing = plan ? (plan.variables || []).filter((v) => !v.has_default && !v.provided && vars[v.name] == null) : [];
  const canApply = !!plan && !busy && toCreate.length > 0 && !(plan.errors || []).length && !rows.some((r) => r.action === "error");

  const apply = async () => {
    setBusy("apply"); setErr(null); setDone(null);
    const p = payload(), order = toCreate.map((r) => r.address);
    let known = {}, created = [], failed = 0;
    setProg({ n: 0, total: order.length });
    const set = (addr, patch) => setRows((rs) => rs.map((r) => (r.address === addr ? { ...r, ...patch } : r)));
    try {
      for (let i = 0; i < order.length; i++) {
        set(order[i], { action: "running" });
        const r = await api.applyBundle(p, [order[i]], known);
        const it = (r.items || []).find((x) => x.address === order[i]) || { action: "failed", reason: "no result" };
        set(order[i], { action: it.action, reason: it.reason, id: it.id, outputs: it.outputs });
        if (it.action === "failed" || it.action === "error" || it.action === "blocked") failed++;
        known = { ...known, ...(r.known || {}) }; created = created.concat(r.ledger || []);
        setProg({ n: i + 1, total: order.length });
      }
    } catch (e) { setErr(e); failed++; }
    const l = [...api.getLedger(), ...created]; api.setLedger(l); setLedger(l);
    setBusy(""); setProg(null); setDone({ created: created.length, failed });
    onChanged && onChanged();
  };

  const destroy = async () => {
    setConfirm(false); setBusy("destroy"); setErr(null);
    try {
      const r = await api.destroyBundle(ledger);
      setRows((rs) => rs.map((x) => { const d = (r.items || []).find((i) => i.address === x.address); return d ? { ...x, action: d.action, reason: d.reason } : x; }));
      const left = (r.items || []).filter((i) => i.action === "failed").map((i) => ledger.find((e) => e.address === i.address)).filter(Boolean);
      api.setLedger(left); setLedger(left); setDone({ destroyed: (r.summary || {}).destroyed || 0, failed: (r.summary || {}).failed || 0 });
      onChanged && onChanged();
    } catch (e) { setErr(e); } finally { setBusy(""); }
  };

  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" description="Drop or paste Terraform to create it in Vyomi through the same AWS API your SDK uses. Resources already in Vyomi are left alone, so applying twice changes nothing.">Import Terraform</Header>}>
        <SpaceBetween size="m">
          <FileUpload multiple value={uploads} onChange={({ detail }) => onUpload(detail.value)} accept=".tf,.tfvars,.zip" showFileLastModified={false} constraintText=".tf and .tfvars files or a .zip (the export zip works as is)"
            i18nStrings={{ uploadButtonText: (m) => (m ? "Choose files" : "Choose file"), dropzoneText: (m) => (m ? "Drop files to upload" : "Drop file to upload"), removeFileAriaLabel: (i) => `Remove file ${i + 1}`, limitShowFewer: "Show fewer files", limitShowMore: "Show more files", errorIconAriaLabel: "Error" }} />
          <FormField label="Or paste Terraform" stretch>
            <Textarea value={pasted} rows={5} placeholder={'resource "aws_s3_bucket" "demo" {\n  bucket = "my-demo-bucket"\n}'} onChange={({ detail }) => { setPasted(detail.value); setDone(null); }} />
          </FormField>
          {missing.length > 0 && <Alert type="info" header="Variables without a value">
            <SpaceBetween size="xs">{missing.map((v) => <FormField key={v.name} label={`var.${v.name}`}><Input type={v.sensitive ? "password" : "text"} value={vars[v.name] || ""} onChange={({ detail }) => setVars((x) => ({ ...x, [v.name]: detail.value }))} /></FormField>)}</SpaceBetween>
          </Alert>}
        </SpaceBetween>
      </Container>
      {err && <Alert type="error" header="Import failed">{String(err.message || err)}</Alert>}
      {plan && (plan.errors || []).length > 0 && <Alert type="error" header="Terraform could not be read">{plan.errors.map((e, i) => <div key={i}>{e.file}{e.line ? `:${e.line}` : ""} {e.error}</div>)}</Alert>}
      {done && <Alert type={done.failed ? "warning" : "success"} header={done.destroyed != null ? `Destroyed ${done.destroyed} resources${done.failed ? `, ${done.failed} failed` : ""}` : done.created === 0 && !done.failed ? "No changes: everything is already in Vyomi" : `Created ${done.created} resources${done.failed ? `, ${done.failed} failed` : ""}`}
        action={<Button onClick={onShowDiagram}>Show diagram</Button>}>The diagram has been refreshed.</Alert>}
      {sum && sum.no_changes && !done && <Alert type="success" header="No changes">Everything in this Terraform is already in Vyomi.</Alert>}
      {(rows.length > 0 || busy === "plan") && (
        <Table items={rows} loading={busy === "plan"} loadingText="Reading the plan" variant="container" trackBy="address"
          header={<Header variant="h2" counter={rows.length ? `(${rows.length})` : undefined} description={sum ? tally(rows) : undefined}
            actions={<SpaceBetween direction="horizontal" size="xs">
              <Button disabled={!ledger.length || !!busy} onClick={() => setConfirm(true)}>Destroy what was imported{ledger.length ? ` (${ledger.length})` : ""}</Button>
              <Button variant="primary" disabled={!canApply} loading={busy === "apply"} onClick={apply}>Apply to Vyomi</Button></SpaceBetween>}>Plan</Header>}
          columnDefinitions={[
            { id: "res", header: "Resource", cell: (r) => <b>{r.address}</b>, sortingField: "address" },
            { id: "type", header: "Type", cell: (r) => r.type },
            { id: "avail", header: "In Vyomi", cell: (r) => <Availability a={r.availability} /> },
            { id: "act", header: "Result", cell: (r) => { const [t, l] = ACTION[r.action] || ["info", r.action]; return <StatusIndicator type={t}>{l}</StatusIndicator>; } },
            { id: "id", header: "Id", cell: (r) => r.id || "-" },
            { id: "why", header: "Details", cell: (r) => r.reason || (r.availability && r.availability.status !== "supported" ? r.availability.reason : "") || "-" }]}
          footer={prog ? <ProgressBar value={prog.total ? Math.round((prog.n / prog.total) * 100) : 100} label="Applying to Vyomi" additionalInfo={`${prog.n} of ${prog.total} resources`} /> : undefined} />
      )}
      {plan && rows.length === 0 && !busy && !(plan.errors || []).length && <Alert type="warning">No resource blocks found.</Alert>}
      <Modal visible={confirm} onDismiss={() => setConfirm(false)} header="Destroy imported resources?"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="primary" onClick={destroy}>Destroy</Button></SpaceBetween></Box>}>
        This removes the {ledger.length} resources created by your imports from Vyomi, newest first. Resources that were already in Vyomi are not touched.
      </Modal>
    </SpaceBetween>
  );
}

export default function Studio() {
  const [base, setBase] = useState(api.getBase());
  const [key, setKey] = useState(0), [tab, setTab] = useState("export"), [ek, setEk] = useState(0);
  return (
    <ContentLayout header={<Header variant="h1" description="See your AWS stack as a diagram, export it as Terraform, or import Terraform to create it in Vyomi."
      actions={<SpaceBetween direction="horizontal" size="xs"><Box variant="small" padding={{ top: "xs" }}>Backend</Box>
        <Input value={base} placeholder="this page" onChange={({ detail }) => setBase(detail.value)} onBlur={() => { api.setBase(base); setKey((k) => k + 1); }} /></SpaceBetween>}>Infrastructure Studio</Header>}>
      <Tabs key={key} activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)}
        tabs={[{ id: "export", label: "Export", content: <ExportTab key={ek} /> }, { id: "import", label: "Import", content: <ImportTab onChanged={() => setEk((k) => k + 1)} onShowDiagram={() => setTab("export")} /> }]} />
    </ContentLayout>
  );
}
