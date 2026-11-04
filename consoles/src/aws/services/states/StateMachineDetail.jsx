import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import Toggle from "@cloudscape-design/components/toggle";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const smArn = (name) => `arn:aws:states:us-east-1:000000000000:stateMachine:${name}`;
const LOG_LEVELS = [{ value: "OFF", label: "OFF" }, { value: "ERROR", label: "ERROR" }, { value: "ALL", label: "ALL" }];
const execStatus = (s) => ({ RUNNING: "in-progress", SUCCEEDED: "success", FAILED: "error", ABORTED: "stopped", TIMED_OUT: "error", PENDING_REDRIVE: "pending" }[s] || "pending");

function EditDefinitionModal({ arn, definition, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [text, setText] = useState(definition);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.updateStateMachine({ stateMachineArn: arn, definition: text }); notify.success("Definition updated."); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} size="large" onDismiss={onDismiss} header="Edit state machine definition"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      {error && <ErrorAlert error={error} />}
      <FormField label="Definition"><Textarea rows={16} spellcheck={false} value={text} onChange={({ detail }) => setText(detail.value)} ariaLabel="Definition" /></FormField>
    </Modal>
  );
}

function EditLoggingModal({ arn, d, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [level, setLevel] = useState(d.loggingConfiguration?.level || "OFF");
  const [includeData, setIncludeData] = useState(!!d.loggingConfiguration?.includeExecutionData);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.updateStateMachine({ stateMachineArn: arn, loggingConfiguration: { level, includeExecutionData: includeData, destinations: [] } });
      notify.success("Logging configuration updated."); onDone(); onDismiss();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit logging"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        <FormField label="Log level"><Select selectedOption={LOG_LEVELS.find((l) => l.value === level)} onChange={({ detail }) => setLevel(detail.selectedOption.value)} options={LOG_LEVELS} ariaLabel="Log level" /></FormField>
        <Checkbox checked={includeData} onChange={({ detail }) => setIncludeData(detail.checked)}>Include execution data in logs</Checkbox>
      </SpaceBetween>
    </Modal>
  );
}

function EditTracingModal({ arn, d, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [enabled, setEnabled] = useState(!!d.tracingConfiguration?.enabled);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try { await api.updateStateMachine({ stateMachineArn: arn, tracingConfiguration: { enabled } }); notify.success("X-Ray tracing updated."); onDone(); onDismiss(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit X-Ray tracing"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      <Toggle checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)}>Active tracing</Toggle>
    </Modal>
  );
}

function CreateAliasModal({ arn, versions, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [version, setVersion] = useState(versions[0] || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    if (!name.trim() || !version) return;
    setBusy(true); setError(null);
    try {
      await api.createAlias(name, [{ stateMachineVersionArn: version.value, weight: 100 }]);
      notify.success(`Created alias "${name}".`); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create alias"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!versions.length} onClick={submit}>Create alias</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        {!versions.length && <ErrorAlert error={{ code: "No versions", message: "Publish a version before creating an alias." }} />}
        <FormField label="Alias name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Alias name" /></FormField>
        <FormField label="Version"><Select selectedOption={version} onChange={({ detail }) => setVersion(detail.selectedOption)} options={versions} ariaLabel="Version" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

function Executions({ name, arn }) {
  const t = useAsync(() => api.listExecutions(arn), [arn]);
  return (
    <Table
      variant="container"
      items={t.data || []}
      loading={t.loading}
      trackBy="executionArn"
      header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
          <Button variant="primary" href={href("states", "state-machines", name, "start")} onFollow={follow}>Start execution</Button>
        </SpaceBetween>
      }>Executions</Header>}
      columnDefinitions={[
        { id: "name", header: "Name", isRowHeader: true, cell: (e) => <Link href={href("states", "state-machines", name, "executions", e.name)} onFollow={follow}>{e.name}</Link> },
        { id: "status", header: "Status", cell: (e) => <StatusIndicator type={execStatus(e.status)}>{e.status}</StatusIndicator> },
        { id: "start", header: "Start time", cell: (e) => fmtDate(e.startDate) },
        { id: "end", header: "End time", cell: (e) => (e.stopDate ? fmtDate(e.stopDate) : "-") },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No executions</b><Box variant="p" color="inherit">This state machine has not been run yet.</Box></Box>}
    />
  );
}

function Definition({ d, reload }) {
  const [editDef, setEditDef] = useState(false);
  const [editLog, setEditLog] = useState(false);
  const [editTrace, setEditTrace] = useState(false);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Definition" actions={<Button onClick={() => setEditDef(true)}>Edit</Button>} columns={1}
        items={[["Definition", <Box variant="code" key="def"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{d.definition}</pre></Box>], ["Type", d.type === "EXPRESS" ? "Express" : "Standard"]]} />
      <KeyValue title="Permissions" columns={1} items={[["Execution role", d.roleArn]]} />
      <CapabilityContainer id="aws.states.state-machine.logging" title="Logging" actions={<Button onClick={() => setEditLog(true)}>Edit</Button>}>
        <KeyValue columns={2} items={[["Log level", d.loggingConfiguration?.level || "OFF"], ["Include execution data in logs", d.loggingConfiguration?.includeExecutionData ? "On" : "Off"]]} />
      </CapabilityContainer>
      <CapabilityContainer id="aws.states.state-machine.tracing" title="X-Ray tracing" actions={<Button onClick={() => setEditTrace(true)}>Edit</Button>}>
        <KeyValue columns={1} items={[["Active tracing", d.tracingConfiguration?.enabled ? "On" : "Off"]]} />
      </CapabilityContainer>
      <EditDefinitionModal arn={d.stateMachineArn} definition={d.definition} visible={editDef} onDismiss={() => setEditDef(false)} onDone={reload} />
      <EditLoggingModal arn={d.stateMachineArn} d={d} visible={editLog} onDismiss={() => setEditLog(false)} onDone={reload} />
      <EditTracingModal arn={d.stateMachineArn} d={d} visible={editTrace} onDismiss={() => setEditTrace(false)} onDone={reload} />
    </SpaceBetween>
  );
}

function Aliases({ arn }) {
  const notify = useNotify();
  const t = useAsync(() => api.listAliases(arn), [arn]);
  const v = useAsync(() => api.listVersions(arn), [arn]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const versionOptions = (v.data || []).map((x) => ({ value: x.stateMachineVersionArn, label: `Version ${x.stateMachineVersionArn.split(":").pop()}` }));
  return (
    <>
      <Table
        variant="container"
        items={t.data || []}
        loading={t.loading}
        trackBy="stateMachineAliasArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create alias</Button>
          </SpaceBetween>
        }>Aliases</Header>}
        columnDefinitions={[
          { id: "name", header: "Name", cell: (a) => a.name },
          { id: "routing", header: "Routing", cell: (a) => (a.routingConfiguration || []).map((r) => `${r.stateMachineVersionArn.split(":").pop()}:${r.weight}%`).join(", ") },
          { id: "created", header: "Created", cell: (a) => fmtDate(a.creationDate) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No aliases</b></Box>}
      />
      <CreateAliasModal arn={arn} versions={versionOptions} visible={create} onDismiss={() => setCreate(false)} onDone={t.reload} />
      <DeleteModal visible={del} resourceType="alias" names={sel.map((a) => a.name)} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const a of sel) await api.deleteAlias(a.stateMachineAliasArn); notify.success("Alias deleted."); setSel([]); t.reload(); }} />
    </>
  );
}

function Versions({ arn }) {
  const notify = useNotify();
  const t = useAsync(() => api.listVersions(arn), [arn]);
  const publish = async () => { try { await api.publishVersion(arn); notify.success("Published a new version."); t.reload(); } catch (e) { notify.error(e); } };
  return (
    <Table
      variant="container"
      items={t.data || []}
      loading={t.loading}
      trackBy="stateMachineVersionArn"
      header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button variant="primary" onClick={publish}>Publish new version</Button>}>Versions</Header>}
      columnDefinitions={[
        { id: "v", header: "Version", cell: (x) => x.stateMachineVersionArn.split(":").pop() },
        { id: "c", header: "Created", cell: (x) => fmtDate(x.creationDate) },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No versions</b></Box>}
    />
  );
}

function TagsTab({ arn }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTags(arn), [arn]);
  const [manage, setManage] = useState(false);
  const [draft, setDraft] = useState([]);
  const open = () => { setDraft((t.data || []).map((x) => ({ key: x.key, value: x.value }))); setManage(true); };
  const save = async () => {
    const existing = t.data || [];
    const keep = draft.filter((x) => x.key);
    const removed = existing.filter((e) => !keep.some((k) => k.key === e.key));
    if (removed.length) await api.untagResource(arn, removed.map((r) => r.key));
    if (keep.length) await api.tagResource(arn, keep);
    notify.success("Tags updated."); setManage(false); t.reload();
  };
  return (
    <>
      <Table
        variant="container"
        items={t.data || []}
        loading={t.loading}
        trackBy="key"
        header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button onClick={open}>Manage tags</Button>}>Tags</Header>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.key }, { id: "v", header: "Value", cell: (x) => x.value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>}
      />
      <Modal visible={manage} onDismiss={() => setManage(false)} header="Manage tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setManage(false)}>Cancel</Button><Button variant="primary" onClick={save}>Save changes</Button></SpaceBetween></Box>}>
        <SpaceBetween size="s">
          {draft.map((row, i) => (
            <SpaceBetween key={i} direction="horizontal" size="xs">
              <FormField label="Key"><Input value={row.key} onChange={({ detail }) => setDraft(draft.map((r, j) => (j === i ? { ...r, key: detail.value } : r)))} ariaLabel="Tag key" /></FormField>
              <FormField label="Value"><Input value={row.value} onChange={({ detail }) => setDraft(draft.map((r, j) => (j === i ? { ...r, value: detail.value } : r)))} ariaLabel="Tag value" /></FormField>
              <Button onClick={() => setDraft(draft.filter((_, j) => j !== i))}>Remove</Button>
            </SpaceBetween>
          ))}
          <Button onClick={() => setDraft([...draft, { key: "", value: "" }])}>Add new tag</Button>
        </SpaceBetween>
      </Modal>
    </>
  );
}

export default function StateMachineDetail({ params, query }) {
  const name = params.name;
  const arn = smArn(name);
  const [tab, setTab] = useState(query.tab || "executions");
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeStateMachine(arn), [arn]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => setDel(true)}>Delete</Button>
        <Button variant="primary" href={href("states", "state-machines", name, "start")} onFollow={follow}>Start execution</Button>
      </SpaceBetween>
    }>{name}</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "executions", label: "Executions", content: <Executions name={name} arn={arn} /> },
        { id: "definition", label: "Definition", content: <Definition d={d} reload={t.reload} /> },
        { id: "aliases", label: "Aliases", content: <Aliases arn={arn} /> },
        { id: "versions", label: "Versions", content: <Versions arn={arn} /> },
        { id: "tags", label: "Tags", content: <TagsTab arn={arn} /> },
      ]} />
      <DeleteModal visible={del} resourceType="state machine" names={[name]} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteStateMachine(arn); navigate("states", "state-machines"); }} />
    </ContentLayout>
  );
}
