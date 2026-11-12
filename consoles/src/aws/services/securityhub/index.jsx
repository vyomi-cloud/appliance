/* Security Hub (summary, findings table + finding detail + workflow status update, controls) and GuardDuty (detector, findings,
 * archive, sample findings) over the native REST-JSON wires (core/secscan_core.py). Findings are derived live from the simulated
 * resources by Vyomi's own rules (see core/capabilities/aws/securityhub.json for the exact control set). */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { awsRest } from "../../../common/wire.js";
import { follow, useRoute } from "../../../common/router.js";

const H = (m, p, o) => awsRest("securityhub", m, p, o);
const GD = (m, p, o) => awsRest("guardduty", m, p, o);
const hubStatus = () => H("GET", "/accounts").then((r) => ({ enabled: true, ...r }), (e) => (/not subscribed|InvalidAccess/i.test(e.message + e.code) ? { enabled: false } : Promise.reject(e)));
const findings = (Filters) => H("POST", "/findings", { body: { MaxResults: 100, ...(Filters ? { Filters } : {}) } }).then((r) => r.Findings || []);
const sevType = (l) => (l === "CRITICAL" || l === "HIGH" ? "error" : l === "MEDIUM" ? "warning" : "info");
const SevBadge = ({ l }) => <Badge color={l === "CRITICAL" ? "severity-critical" : l === "HIGH" ? "severity-high" : l === "MEDIUM" ? "severity-medium" : l === "LOW" ? "severity-low" : "grey"}>{l}</Badge>;

function EnableGate({ children }) {
  const notify = useNotify();
  const s = useAsync(hubStatus, []);
  if (s.error) return <ErrorAlert error={s.error} />;
  if (s.loading) return null;
  if (!s.data.enabled) return (
    <ContentLayout header={<Header variant="h1">Security Hub</Header>}>
      <Container header={<Header variant="h2">Enable Security Hub</Header>}><SpaceBetween size="m">
        <Box>Security Hub aggregates findings that Vyomi derives from your simulated resources (S3, EC2, RDS, IAM, CloudTrail) with AWS Foundational Security Best Practices controls.</Box>
        <Button variant="primary" onClick={async () => { try { await H("POST", "/accounts", { body: { EnableDefaultStandards: true } }); notify.success("Security Hub enabled."); s.reload(); } catch (e) { notify.error(e); } }}>Enable Security Hub</Button>
      </SpaceBetween></Container>
    </ContentLayout>);
  return children(s);
}

function Summary() {
  return <EnableGate>{() => <SummaryBody />}</EnableGate>;
}
function SummaryBody() {
  const t = useAsync(() => H("POST", "/findings/stats", { body: {} }), []);
  const notify = useNotify();
  const d = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={async () => { try { await H("DELETE", "/accounts"); notify.success("Security Hub disabled."); location.reload(); } catch (e) { notify.error(e); } }}>Disable Security Hub</Button>}>Security Hub summary</Header>}>
      <SpaceBetween size="l"><ErrorAlert error={t.error} />
        <Container header={<Header variant="h2" description="Active findings by severity label">Findings</Header>}>
          <ColumnLayout columns={5} variant="text-grid">
            {["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"].map((l) => <div key={l}><Box variant="awsui-key-label"><SevBadge l={l} /></Box><Box variant="awsui-value-large" data-testid={`sev-${l}`}>{d ? d.BySeverity[l] : "-"}</Box></div>)}
          </ColumnLayout>
          <Box margin={{ top: "m" }}><Link href="#/securityhub/findings" onFollow={follow}>View all {d?.Total ?? ""} findings</Link></Box>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}

const WF = ["NEW", "NOTIFIED", "SUPPRESSED", "RESOLVED"];
function Findings() {
  return <EnableGate>{() => <FindingsBody />}</EnableGate>;
}
function FindingsBody() {
  const notify = useNotify();
  const [sev, setSev] = useState({ label: "All severities", value: "" });
  const filt = sev.value ? { SeverityLabel: [{ Value: sev.value, Comparison: "EQUALS" }] } : undefined;
  const t = useAsync(() => findings(filt), [sev.value]);
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(null);
  const [upd, setUpd] = useState(false);
  const [wf, setWf] = useState(WF[1]);
  const [note, setNote] = useState("");
  return (
    <>
      <ResourceTable resourceName="Findings" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="Id" selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter findings"
        empty={{ title: "No findings" }}
        columns={[{ id: "s", header: "Severity", cell: (f) => <SevBadge l={f.Severity.Label} />, sortingField: "Title" },
          { id: "w", header: "Workflow status", cell: (f) => f.Workflow.Status }, { id: "r", header: "Record state", cell: (f) => f.RecordState },
          { id: "c", header: "Company", cell: (f) => f.CompanyName }, { id: "p", header: "Product", cell: (f) => f.ProductName },
          { id: "t", header: "Title", isRowHeader: true, cell: (f) => <Button variant="link" onClick={() => setOpen(f)}>{f.Title}</Button> },
          { id: "rt", header: "Resource", cell: (f) => f.Resources[0].Id }, { id: "cs", header: "Compliance", cell: (f) => f.Compliance?.Status || "-" }]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Select ariaLabel="Severity filter" selectedOption={sev} onChange={({ detail }) => setSev(detail.selectedOption)} options={[{ label: "All severities", value: "" }, ...["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"].map((l) => ({ label: l, value: l }))]} />
          <Button disabled={!sel.length} onClick={() => setUpd(true)}>Update workflow status</Button></SpaceBetween>} />
      <Modal visible={!!open} size="large" onDismiss={() => setOpen(null)} header={open?.Title || ""}
        footer={<Box float="right"><Button onClick={() => setOpen(null)}>Close</Button></Box>}>
        {open && <SpaceBetween size="m">
          <KeyValue columns={2} items={[["Severity", open.Severity.Label], ["Workflow status", open.Workflow.Status], ["Product", open.ProductName], ["Control / generator", open.GeneratorId], ["Resource", `${open.Resources[0].Type} ${open.Resources[0].Id}`], ["Compliance", open.Compliance?.Status], ["First observed", fmtDate(open.FirstObservedAt)], ["Updated", fmtDate(open.UpdatedAt)]]} />
          <Container header={<Header variant="h3">Description</Header>}>{open.Description}</Container>
          <Container header={<Header variant="h3">Remediation</Header>}>{open.Remediation?.Recommendation?.Text}</Container>
          <Tabs tabs={[{ id: "j", label: "Finding JSON (ASFF)", content: <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap", maxHeight: 280, overflow: "auto" }}>{JSON.stringify(open, null, 2)}</pre></Box> }]} />
        </SpaceBetween>}
      </Modal>
      <Modal visible={upd} onDismiss={() => setUpd(false)} header="Update workflow status"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setUpd(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { const r = await H("PATCH", "/findings/batchupdate", { body: { FindingIdentifiers: sel.map((f) => ({ Id: f.Id, ProductArn: f.ProductArn })), Workflow: { Status: wf }, ...(note ? { Note: { Text: note, UpdatedBy: "console" } } : {}) } }); notify.success(`Updated ${r.ProcessedFindings.length} finding(s) to ${wf}.`); setUpd(false); setSel([]); t.reload(); } catch (e) { notify.error(e); } }}>Update</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><FormField label="Workflow status"><Select ariaLabel="Workflow status" selectedOption={{ label: wf, value: wf }} onChange={({ detail }) => setWf(detail.selectedOption.value)} options={WF.map((w) => ({ label: w, value: w }))} /></FormField>
          <FormField label="Note (optional)"><Input ariaLabel="Note" value={note} onChange={({ detail }) => setNote(detail.value)} /></FormField></SpaceBetween>
      </Modal>
    </>
  );
}

function Controls() {
  return <EnableGate>{() => <ControlsBody />}</EnableGate>;
}
function ControlsBody() {
  const t = useAsync(() => findings(), []);
  const byControl = {};
  for (const f of t.data || []) { if (f.ProductName !== "Security Hub") continue; const c = f.ProductFields?.ControlId || f.GeneratorId.split("/").pop(); (byControl[c] ||= { control: c, title: f.Title, sev: f.Severity.Label, failed: 0, passed: 0 })[f.Compliance?.Status === "PASSED" ? "passed" : "failed"]++; }
  return (
    <ResourceTable resourceName="Controls" items={Object.values(byControl)} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="control" filterPlaceholder="Filter controls" empty={{ title: "No control findings" }}
      columns={[{ id: "c", header: "Control ID", isRowHeader: true, cell: (c) => c.control }, { id: "t", header: "Title", cell: (c) => c.title }, { id: "s", header: "Severity", cell: (c) => <SevBadge l={c.sev} /> },
        { id: "st", header: "Status", cell: (c) => (c.failed ? <StatusIndicator type="error">Failed ({c.failed})</StatusIndicator> : <StatusIndicator type="success">Passed</StatusIndicator>) }]} />
  );
}

// ── GuardDuty ──
const detectors = () => GD("GET", "/detector").then((r) => r.DetectorIds || []);
function GuardDuty() {
  const notify = useNotify();
  const d = useAsync(detectors, []);
  const id = (d.data || [])[0];
  const f = useAsync(async () => {
    if (!id) return [];
    const ids = (await GD("POST", `/detector/${id}/findings`, { body: {} })).FindingIds;
    return ids.length ? (await GD("POST", `/detector/${id}/findings/get`, { body: { FindingIds: ids } })).Findings : [];
  }, [id]);
  const [sel, setSel] = useState([]);
  if (d.loading) return null;
  if (!id) return (
    <ContentLayout header={<Header variant="h1">GuardDuty</Header>}><Container header={<Header variant="h2">Enable GuardDuty</Header>}><SpaceBetween size="m">
      <Box>GuardDuty analyses the simulator's own API activity feed (CloudTrail-style events) for threats such as public bucket policies and credential misuse.</Box>
      <Button variant="primary" onClick={async () => { try { await GD("POST", "/detector", { body: { Enable: true } }); notify.success("GuardDuty enabled."); d.reload(); } catch (e) { notify.error(e); } }}>Enable GuardDuty</Button></SpaceBetween></Container></ContentLayout>);
  return (
    <ResourceTable resourceName="GuardDuty findings" items={f.data || []} loading={f.loading} error={f.error} onRefresh={f.reload} trackBy="Id" selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter findings"
      empty={{ title: "No findings", subtitle: "Generate sample findings to see the finding format." }}
      columns={[{ id: "s", header: "Severity", cell: (x) => <StatusIndicator type={x.Severity >= 7 ? "error" : x.Severity >= 4 ? "warning" : "info"}>{x.Severity >= 7 ? "High" : x.Severity >= 4 ? "Medium" : "Low"} ({x.Severity})</StatusIndicator> },
        { id: "t", header: "Finding type", isRowHeader: true, cell: (x) => x.Type }, { id: "r", header: "Resource", cell: (x) => x.Resource?.ResourceType }, { id: "ti", header: "Title", cell: (x) => x.Title },
        { id: "a", header: "Archived", cell: (x) => (x.Service?.Archived ? "Yes" : "No") }, { id: "u", header: "Last seen", cell: (x) => x.UpdatedAt }]}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button onClick={async () => { try { await GD("POST", `/detector/${id}/findings/create`, { body: {} }); notify.success("Sample findings generated."); f.reload(); } catch (e) { notify.error(e); } }}>Generate sample findings</Button>
        <Button disabled={!sel.length} onClick={async () => { await GD("POST", `/detector/${id}/findings/archive`, { body: { FindingIds: sel.map((x) => x.Id) } }); setSel([]); f.reload(); }}>Archive</Button></SpaceBetween>} />
  );
}

const root = { text: "Security Hub", href: "#/securityhub" };
export default {
  nav: [{ type: "link", text: "Summary", href: "#/securityhub" }, { type: "link", text: "Findings", href: "#/securityhub/findings" }, { type: "link", text: "Controls", href: "#/securityhub/controls" },
    { type: "divider" }, { type: "link", text: "GuardDuty findings", href: "#/securityhub/guardduty" }],
  routes: [
    { pattern: "/securityhub", component: Summary, crumbs: () => [root] },
    { pattern: "/securityhub/findings", component: Findings, crumbs: () => [root, { text: "Findings", href: "#/securityhub/findings" }] },
    { pattern: "/securityhub/controls", component: Controls, crumbs: () => [root, { text: "Controls", href: "#/securityhub/controls" }] },
    { pattern: "/securityhub/guardduty", component: GuardDuty, crumbs: () => [root, { text: "GuardDuty findings", href: "#/securityhub/guardduty" }] },
  ],
};
