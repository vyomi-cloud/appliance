/* EventBridge bus/archive settings backed by real backends (sweep AWS-08): customer KMS key,
 * bus logs -> CloudWatch Logs, resource-based policy (PutPermission / enforcement on cross-account PutEvents). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import Input from "@cloudscape-design/components/input";
import { KeyValue, ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const DEFAULT_KEY = { value: "", label: "Use AWS owned key" };

export function KmsKeySelect({ value, onChange, label = "AWS Key Management Service (KMS) key" }) {
  const keys = useAsync(() => api.listKmsKeys(), []);
  const opts = [DEFAULT_KEY, ...(keys.data || []).map((k) => ({ value: k.KeyId, label: k.KeyId, description: k.Description || undefined }))];
  return (
    <FormField label={label} description="Choose a customer managed key; events are stored as KMS ciphertext. Keys are listed from this account's KMS.">
      <Select ariaLabel="KMS key" selectedOption={opts.find((o) => o.value === value) || (value ? { value, label: value } : DEFAULT_KEY)}
        options={opts} statusType={keys.loading ? "loading" : "finished"} onChange={({ detail }) => onChange(detail.selectedOption.value)} />
    </FormField>
  );
}

const LEVELS = ["OFF", "ERROR", "INFO", "TRACE"].map((v) => ({ value: v, label: v }));
const DETAIL = [{ value: "NONE", label: "None" }, { value: "FULL", label: "Full" }];

export function LogConfigFields({ value, onChange }) {
  const v = value || { Level: "OFF", IncludeDetail: "NONE" };
  return (
    <SpaceBetween size="l">
      <FormField label="Log destination" description="CloudWatch Logs log group /aws/vendedlogs/events/event-bus/<bus> (created on first record).">
        <Box variant="span">CloudWatch Logs</Box>
      </FormField>
      <FormField label="Log level">
        <Select ariaLabel="Log level" selectedOption={LEVELS.find((l) => l.value === v.Level)} options={LEVELS} onChange={({ detail }) => onChange({ ...v, Level: detail.selectedOption.value })} />
      </FormField>
      <FormField label="Include execution data">
        <Select ariaLabel="Include execution data" selectedOption={DETAIL.find((l) => l.value === v.IncludeDetail)} options={DETAIL} onChange={({ detail }) => onChange({ ...v, IncludeDetail: detail.selectedOption.value })} />
      </FormField>
    </SpaceBetween>
  );
}

export function PolicyField({ value, onChange }) {
  return (
    <FormField label="Resource-based policy" description="Evaluated on cross-account PutEvents (x-amz-account-id). An account needs an explicit events:PutEvents Allow.">
      <Textarea ariaLabel="Resource-based policy" rows={8} value={value} onChange={({ detail }) => onChange(detail.value)}
        placeholder={'{\n  "Version": "2012-10-17",\n  "Statement": [{ "Sid": "AllowAccount", "Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::111122223333:root"}, "Action": "events:PutEvents", "Resource": "<bus arn>" }]\n}'} />
    </FormField>
  );
}

export function EncryptionTab({ bus, reload }) {
  const notify = useNotify();
  const [key, setKey] = useState(null);
  const [busy, setBusy] = useState(false);
  const cur = bus.KmsKeyIdentifier || "";
  const shown = key ?? cur;
  const save = async () => {
    setBusy(true);
    try { await api.updateEventBusConfig(bus.Name, { KmsKeyIdentifier: shown }); notify.success("Encryption updated. New events use the selected key."); setKey(null); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2">Encryption</Header>}>
      <SpaceBetween size="l">
        <KeyValue columns={2} items={[["Encryption", cur ? "Customer managed key" : "AWS owned key"], ["KMS key", cur || "-"]]} />
        <KmsKeySelect value={shown} onChange={setKey} />
        <Box float="left"><Button loading={busy} onClick={save} disabled={shown === cur}>Save</Button></Box>
      </SpaceBetween>
    </Container>
  );
}

export function PermissionsTab({ bus, reload }) {
  const notify = useNotify();
  const [text, setText] = useState(null);
  const [busy, setBusy] = useState(false);
  const [acct, setAcct] = useState("");
  const [sid, setSid] = useState("");
  let doc = null;
  try { doc = bus.Policy ? JSON.parse(bus.Policy) : null; } catch { /* ignore */ }
  const statements = doc?.Statement || [];
  const run = async (fn, ok) => { setBusy(true); try { await fn(); notify.success(ok); setText(null); reload(); } catch (e) { notify.error(e); } finally { setBusy(false); } };
  return (
    <SpaceBetween size="l">
      <Table variant="container" header={<Header variant="h2" counter={`(${statements.length})`}>Resource-based policy statements</Header>}
        items={statements} trackBy="Sid" empty={<Box textAlign="center" color="inherit">No policy. Only this account can put events to the bus.</Box>}
        columnDefinitions={[
          { id: "sid", header: "Statement ID", cell: (s) => s.Sid },
          { id: "effect", header: "Effect", cell: (s) => s.Effect },
          { id: "principal", header: "Principal", cell: (s) => JSON.stringify(s.Principal) },
          { id: "action", header: "Action", cell: (s) => [].concat(s.Action).join(", ") },
          { id: "rm", header: "", cell: (s) => <Button variant="inline-link" onClick={() => run(() => api.removePermission({ EventBusName: bus.Name, StatementId: s.Sid }), `Removed statement ${s.Sid}.`)}>Remove</Button> },
        ]} />
      <Container header={<Header variant="h2">Allow an account to put events</Header>}>
        <SpaceBetween size="m" direction="horizontal">
          <FormField label="Statement ID"><Input ariaLabel="Statement ID" value={sid} onChange={({ detail }) => setSid(detail.value)} /></FormField>
          <FormField label="Account ID"><Input ariaLabel="Account ID" value={acct} onChange={({ detail }) => setAcct(detail.value)} /></FormField>
          <Box padding={{ top: "xl" }}><Button loading={busy} disabled={!sid || !acct} onClick={() => run(() => api.putPermission({ EventBusName: bus.Name, StatementId: sid, Principal: acct, Action: "events:PutEvents" }), `Allowed account ${acct}.`)}>Add statement</Button></Box>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2">Edit policy document</Header>}>
        <SpaceBetween size="m">
          <PolicyField value={text ?? (doc ? JSON.stringify(doc, null, 2) : "")} onChange={setText} />
          <Box float="left"><Button loading={busy} disabled={text === null || !text.trim()} onClick={() => run(() => api.updateEventBusConfig(bus.Name, { Policy: text }), "Policy saved.")}>Save policy</Button></Box>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}

export function LogsTab({ bus, reload }) {
  const notify = useNotify();
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);
  const events = useAsync(() => api.busLogEvents(bus.Name), [bus.Name]);
  const shown = cfg ?? bus.LogConfig ?? { Level: "OFF", IncludeDetail: "NONE" };
  const save = async () => {
    setBusy(true);
    try { await api.updateEventBusConfig(bus.Name, { LogConfig: shown }); notify.success("Log configuration updated."); setCfg(null); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Logs</Header>}>
        <SpaceBetween size="l">
          <LogConfigFields value={shown} onChange={setCfg} />
          <Box float="left"><Button loading={busy} onClick={save} disabled={cfg === null}>Save</Button></Box>
        </SpaceBetween>
      </Container>
      <Table variant="container" header={<Header variant="h2" actions={<Button iconName="refresh" onClick={events.reload} ariaLabel="Refresh log records" />}>Log records ({api.busLogGroup(bus.Name)})</Header>}
        items={events.data || []} trackBy="eventId" empty={<Box textAlign="center" color="inherit">No log records yet. Set a log level and put an event.</Box>}
        columnDefinitions={[
          { id: "t", header: "Time", cell: (e) => new Date(e.timestamp).toLocaleString() },
          { id: "m", header: "Record", cell: (e) => <code style={{ whiteSpace: "pre-wrap" }}>{e.message}</code> },
        ]} />
    </SpaceBetween>
  );
}
