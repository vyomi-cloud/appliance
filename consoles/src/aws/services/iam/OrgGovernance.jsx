/* AWS Organizations governance: the organization tree with the SCPs / RCPs attached to every root, OU and account (attach / detach through
 * the native Organizations API), the effective policies of an account (the levels the engine evaluates), a "check" that runs an action
 * through that chain, and the policy editor for new SCPs / RCPs. Reads: GET /api/iam/aws/governance/{organization,effective}; writes are the
 * Organizations wire (AttachPolicy, DetachPolicy, CreatePolicy, UpdatePolicy). */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import Toggle from "@cloudscape-design/components/toggle";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { gov } from "../../../common/governanceApi.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const TEMPLATES = {
  "Deny an action": { Effect: "Deny", Action: ["s3:DeleteBucket"], Resource: "*" },
  "Deny outside regions": { Effect: "Deny", NotAction: ["iam:*", "sts:*"], Resource: "*", Condition: { StringNotEquals: { "aws:RequestedRegion": ["us-east-1", "eu-west-1"] } } },
  "Allow-list a service": { Effect: "Allow", Action: ["s3:*"], Resource: "*" },
};
const RCP_TEMPLATE = { Effect: "Deny", Principal: "*", Action: ["s3:*"], Resource: "*", Condition: { Bool: { "aws:SecureTransport": "false" } } };

/** Validated JSON policy editor (same document model as IAM's JSON editor) with statement templates. */
function PolicyJsonEditor({ value, onChange, rcp }) {
  let err = null;
  try { const d = JSON.parse(value); if (!d || typeof d !== "object" || !d.Statement) err = "A policy needs a Statement element."; } catch (e) { err = `Not valid JSON: ${e.message}`; }
  const add = (st) => { try { const d = JSON.parse(value); d.Statement = [].concat(d.Statement || [], [st]); onChange(JSON.stringify(d, null, 2)); } catch { /* keep text */ } };
  return (
    <SpaceBetween size="xs">
      <SpaceBetween direction="horizontal" size="xs">
        {Object.entries(rcp ? { "Deny non-TLS access": RCP_TEMPLATE } : TEMPLATES).map(([n, st]) =>
          <Button key={n} iconName="add-plus" onClick={() => add(st)}>{n}</Button>)}
      </SpaceBetween>
      <FormField label="Policy document" errorText={err}><Textarea rows={14} value={value} onChange={({ detail }) => onChange(detail.value)} spellcheck={false} ariaLabel="Policy document" /></FormField>
    </SpaceBetween>
  );
}

const BASE = (type) => JSON.stringify({ Version: "2012-10-17", Statement: type === "RESOURCE_CONTROL_POLICY" ? [RCP_TEMPLATE] : [{ Effect: "Allow", Action: "*", Resource: "*" }] }, null, 2);

function CreatePolicyPanel({ onDone }) {
  const notify = useNotify();
  const [type, setType] = useState({ value: "SERVICE_CONTROL_POLICY", label: "Service control policy" });
  const [name, setName] = useState("");
  const [doc, setDoc] = useState(BASE("SERVICE_CONTROL_POLICY"));
  const [busy, setBusy] = useState(false);
  return (
    <Container header={<Header variant="h2">Create policy</Header>}>
      <SpaceBetween size="m">
        <FormField label="Policy type"><Select selectedOption={type} onChange={({ detail }) => { setType(detail.selectedOption); setDoc(BASE(detail.selectedOption.value)); }}
          options={[{ value: "SERVICE_CONTROL_POLICY", label: "Service control policy" }, { value: "RESOURCE_CONTROL_POLICY", label: "Resource control policy" }]} /></FormField>
        <FormField label="Policy name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="New policy name" /></FormField>
        <PolicyJsonEditor value={doc} onChange={setDoc} rcp={type.value === "RESOURCE_CONTROL_POLICY"} />
        <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
          setBusy(true);
          try { await api.orgCreatePolicy(name, "", type.value, doc); notify.success(`Policy "${name}" created.`); setName(""); onDone(); }
          catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Create policy</Button>
      </SpaceBetween>
    </Container>
  );
}

export default function OrgGovernance() {
  const notify = useNotify();
  const tree = useAsync(() => gov("aws", "organization"), []);
  const pols = useAsync(async () => {
    const list = async (t) => { try { return await api.orgListPolicies(t); } catch { return []; } };
    return [...(await list("SERVICE_CONTROL_POLICY")), ...(await list("RESOURCE_CONTROL_POLICY"))];
  }, []);
  const [sel, setSel] = useState([]);
  const [pick, setPick] = useState(null);
  const [account, setAccount] = useState(null);
  const eff = useAsync(() => (account ? gov("aws", "effective", { query: { account: account.value } }) : Promise.resolve(null)), [account?.value]);
  const [check, setCheck] = useState({ action: "s3:DeleteBucket", resource: "*" });
  const [checkOut, setCheckOut] = useState(null);
  const [tab, setTab] = useState("tree");
  if (tree.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (tree.error) return <ErrorAlert error={tree.error} />;
  const t = tree.data;
  if (!t.organization) return <Alert type="info" header="No organization">Create an organization from Service control policies first.</Alert>;
  const nodes = t.nodes;
  const byParent = (p) => nodes.filter((n) => n.parent === p);
  const rows = [];
  const walk = (n, depth) => { rows.push({ ...n, depth }); byParent(n.id).forEach((c) => walk(c, depth + 1)); };
  nodes.filter((n) => n.type === "ROOT").forEach((r) => walk(r, 0));
  const accounts = nodes.filter((n) => n.type === "ACCOUNT").map((a) => ({ value: a.id, label: `${a.name} (${a.id})` }));
  const target = sel[0];
  const attachable = (pols.data || []).filter((p) => !(target?.policies || []).some((x) => x.id === p.Id));
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); tree.reload(); eff.reload(); } catch (e) { notify.error(e); } };
  return (
    <ContentLayout header={<Header variant="h1" description="Attach service control policies and resource control policies to the root, OUs and accounts, and see what applies to an account.">Organization governance</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "tree", label: "Organization structure", content: (
          <SpaceBetween size="m">
            <Table items={rows} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)} variant="container"
              header={<Header variant="h2" counter={`(${rows.length})`}
                actions={<SpaceBetween direction="horizontal" size="xs">
                  <Select selectedOption={pick} onChange={({ detail }) => setPick(detail.selectedOption)} placeholder={target ? `Attach to ${target.name}` : "Select a node first"} ariaLabel="Policy to attach"
                    options={attachable.map((p) => ({ value: p.Id, label: p.Name, description: p.Type === "SERVICE_CONTROL_POLICY" ? "SCP" : "RCP" }))} disabled={!target} />
                  <Button disabled={!target || !pick} onClick={() => act(async () => { await api.orgAttachPolicy(pick.value, target.id); setPick(null); }, "Policy attached.")}>Attach policy</Button>
                </SpaceBetween>}>Roots, OUs and accounts</Header>}
              columnDefinitions={[
                { id: "name", header: "Name", isRowHeader: true, cell: (n) => <span style={{ paddingLeft: n.depth * 20 }}>{n.type === "ACCOUNT" ? "" : "▸ "}{n.name}</span> },
                { id: "type", header: "Type", cell: (n) => n.type === "ORGANIZATIONAL_UNIT" ? "OU" : n.type === "ROOT" ? "Root" : "Account" },
                { id: "id", header: "ID", cell: (n) => n.id },
                { id: "pol", header: "Attached policies", cell: (n) => <SpaceBetween direction="horizontal" size="xxs">{n.policies.map((p) =>
                  <Badge key={p.id} color={p.type === "RESOURCE_CONTROL_POLICY" ? "blue" : p.awsManaged ? "grey" : "red"}>{p.name}{!p.awsManaged && <Button variant="inline-icon" iconName="close" ariaLabel={`Detach ${p.name} from ${n.name}`}
                    onClick={(e) => { e.stopPropagation(); act(() => api.orgDetachPolicy(p.id, n.id), "Policy detached."); }} />}</Badge>)}</SpaceBetween> },
              ]} empty={<Box textAlign="center">No nodes</Box>} />
            <Container header={<Header variant="h2">Management account</Header>}>
              <Toggle checked={t.organization.scpAppliesToManagement} onChange={({ detail }) => act(() => gov("aws", "settings", { method: "POST", body: { scpAppliesToManagement: detail.checked } }), detail.checked ? "SCPs now apply to the management account." : "Management account exempt from SCPs.")}>
                Apply SCPs to the management account (Vyomi lab setting)
              </Toggle>
              <Box variant="small" color="text-body-secondary">AWS never restricts the management account with SCPs. Vyomi runs your IAM users in that one account, so turn this on to see SCPs deny real requests.</Box>
            </Container>
          </SpaceBetween>) },
        { id: "effective", label: "Effective policies", content: (
          <SpaceBetween size="m">
            <FormField label="Account"><Select selectedOption={account} onChange={({ detail }) => setAccount(detail.selectedOption)} options={accounts} placeholder="Choose an account" ariaLabel="Account" /></FormField>
            {eff.error && <ErrorAlert error={eff.error} />}
            {eff.data && (
              <SpaceBetween size="m">
                {eff.data.exemptFromScps && <Alert type="info">The management account is not restricted by SCPs.</Alert>}
                {["scp", "rcp"].map((k) => (
                  <Table key={k} variant="container" items={eff.data[k]} trackBy="node" header={<Header variant="h2">{k === "scp" ? "Service control policies" : "Resource control policies"} in the path (every level must allow; a Deny anywhere wins)</Header>}
                    columnDefinitions={[
                      { id: "n", header: "Inherited from", isRowHeader: true, cell: (l) => `${l.nodeName} (${l.node})` },
                      { id: "p", header: "Policies", cell: (l) => l.policies.map((p) => p.name).join(", ") || "-" },
                    ]} empty={<Box textAlign="center">None attached</Box>} />
                ))}
                <Table variant="container" items={eff.data.denyStatements} header={<Header variant="h2">Deny statements in force</Header>}
                  columnDefinitions={[
                    { id: "k", header: "Type", cell: (d) => d.kind }, { id: "n", header: "Attached at", cell: (d) => d.nodeName }, { id: "p", header: "Policy", cell: (d) => d.policy },
                    { id: "a", header: "Actions", cell: (d) => [].concat(d.actions || []).join(", ") }, { id: "c", header: "Condition", cell: (d) => (d.hasCondition ? "yes" : "no") },
                  ]} empty={<Box textAlign="center">No explicit denies</Box>} />
                <Container header={<Header variant="h2">Test an action against this account</Header>}>
                  <SpaceBetween size="s">
                    <FormField label="Action"><Input value={check.action} onChange={({ detail }) => setCheck({ ...check, action: detail.value })} ariaLabel="Action" /></FormField>
                    <FormField label="Resource"><Input value={check.resource} onChange={({ detail }) => setCheck({ ...check, resource: detail.value })} ariaLabel="Resource" /></FormField>
                    <Button onClick={async () => { try { setCheckOut(await gov("aws", "check", { method: "POST", body: { account: account.value, action: check.action, resource: check.resource } })); } catch (e) { notify.error(e); } }}>Test</Button>
                    {checkOut && <Alert type={checkOut.allowed ? "success" : "error"} header={checkOut.allowed ? "Allowed by the guardrails" : `Denied (${checkOut.reason}${checkOut.failedLayer ? ", " + checkOut.failedLayer : ""})`}>
                      {(checkOut.matched || []).map((m, i) => <div key={i}>{m.source.toUpperCase()}: {m.id}</div>)}</Alert>}
                  </SpaceBetween>
                </Container>
              </SpaceBetween>)}
          </SpaceBetween>) },
        { id: "create", label: "Create policy", content: <CreatePolicyPanel onDone={() => { pols.reload(); tree.reload(); }} /> },
      ]} />
    </ContentLayout>
  );
}
