/* CloudFormation stack policy, rollback configuration (CloudWatch alarm triggers) and SNS notification options.
 * All three are enforced by the CloudFormation core (sweep AWS-08): policy blocks updates, alarms in ALARM trigger a
 * real rollback to the previous template, and every stack event is published to the notification topics. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Multiselect from "@cloudscape-design/components/multiselect";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";
import { KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const SAMPLE = `{
  "Statement": [
    { "Effect": "Allow", "Action": "Update:*", "Principal": "*", "Resource": "*" },
    { "Effect": "Deny", "Action": ["Update:Replace", "Update:Delete"], "Principal": "*", "Resource": "LogicalResourceId/MyResource" }
  ]
}`;

export function StackPolicyPanel({ name }) {
  const notify = useNotify();
  const policy = useAsync(() => api.getStackPolicy(name), [name]);
  const [text, setText] = useState(null);
  const [busy, setBusy] = useState(false);
  const shown = text ?? policy.data ?? "";
  const save = async () => {
    setBusy(true);
    try { await api.setStackPolicy(name, shown); notify.success("Stack policy saved."); setText(null); policy.reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2" description="Protects resources from unintentional updates. Once set, updates are denied unless a statement allows them.">Stack policy</Header>}>
      <SpaceBetween size="m">
        <Textarea ariaLabel="Stack policy document" rows={8} value={shown} placeholder={SAMPLE} spellcheck={false} onChange={({ detail }) => setText(detail.value)} />
        <Box float="left"><Button loading={busy} disabled={text === null || !shown.trim()} onClick={save}>Save stack policy</Button></Box>
      </SpaceBetween>
    </Container>
  );
}

export function RollbackPanel({ d, reload }) {
  const notify = useNotify();
  const alarms = useAsync(() => api.listAlarms(), []);
  const cur = d.RollbackConfiguration?.RollbackTriggers?.member;
  const curArns = (cur ? [].concat(cur) : []).map((t) => t.Arn);
  const [sel, setSel] = useState(null);
  const [mins, setMins] = useState(null);
  const [busy, setBusy] = useState(false);
  const arns = sel ?? curArns;
  const options = (alarms.data || []).map((a) => ({ value: a.arn, label: a.name, description: a.state }));
  const save = async () => {
    setBusy(true);
    try { await api.updateStackSettings(d.StackName, { rollbackAlarms: arns, monitoringMinutes: Number(mins ?? d.RollbackConfiguration?.MonitoringTimeInMinutes ?? 0) }); notify.success("Rollback configuration saved."); setSel(null); setMins(null); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2" description="If any selected alarm is in ALARM after an operation, CloudFormation rolls the stack back to its previous template.">Rollback configuration</Header>}>
      <SpaceBetween size="m">
        <FormField label="Monitoring alarms">
          <Multiselect ariaLabel="Rollback alarms" placeholder="Choose CloudWatch alarms" options={options} selectedOptions={arns.map((a) => options.find((o) => o.value === a) || { value: a, label: a.split(":alarm:")[1] || a })}
            onChange={({ detail }) => setSel(detail.selectedOptions.map((o) => o.value))} statusType={alarms.loading ? "loading" : "finished"} empty="No alarms" />
        </FormField>
        <FormField label="Monitoring time (minutes)"><Input type="number" ariaLabel="Monitoring time" value={String(mins ?? d.RollbackConfiguration?.MonitoringTimeInMinutes ?? 0)} onChange={({ detail }) => setMins(detail.value)} /></FormField>
        <Box float="left"><Button loading={busy} disabled={sel === null && mins === null} onClick={save}>Save rollback configuration</Button></Box>
      </SpaceBetween>
    </Container>
  );
}

export function NotificationsPanel({ d, reload }) {
  const notify = useNotify();
  const cur = d.NotificationARNs?.member ? [].concat(d.NotificationARNs.member) : (Array.isArray(d.NotificationARNs) ? d.NotificationARNs : []);
  const [text, setText] = useState(null);
  const [busy, setBusy] = useState(false);
  const shown = text ?? cur.join(", ");
  const save = async () => {
    setBusy(true);
    try { await api.updateStackSettings(d.StackName, { notificationArns: shown.split(",").map((x) => x.trim()).filter(Boolean) }); notify.success("Notification options saved."); setText(null); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2" description="Every stack event is published to these SNS topics.">Notification options</Header>}>
      <SpaceBetween size="m">
        <FormField label="SNS topic ARNs" description="Comma separated."><Input ariaLabel="Notification topic ARNs" value={shown} onChange={({ detail }) => setText(detail.value)} /></FormField>
        <Box float="left"><Button loading={busy} disabled={text === null} onClick={save}>Save notification options</Button></Box>
      </SpaceBetween>
    </Container>
  );
}
