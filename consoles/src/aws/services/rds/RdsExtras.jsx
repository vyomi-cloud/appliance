/* RDS sweep AWS-09: IAM role association, CloudWatch alarms for a DB instance, Service quotas page. All real backends. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const FEATURES = ["s3Import", "s3Export", "Lambda", "SQLSERVER_BACKUP_RESTORE", "S3_INTEGRATION"];
const toOpt = (v) => ({ value: v, label: v });

export function RolePicker({ role, feature, onRole, onFeature }) {
  const roles = useAsync(() => api.listRdsRoles(), []);
  const ropts = (roles.data || []).map((r) => ({ value: r.arn, label: r.name, description: r.arn }));
  return (
    <SpaceBetween size="l">
      <FormField label="Feature" description="The RDS feature that assumes the role.">
        <Select selectedOption={feature ? toOpt(feature) : null} onChange={({ detail }) => onFeature(detail.selectedOption.value)} placeholder="Choose a feature" options={FEATURES.map(toOpt)} ariaLabel="Feature" />
      </FormField>
      <FormField label="IAM role" description="Roles whose trust policy names rds.amazonaws.com.">
        <Select selectedOption={role ? (ropts.find((o) => o.value === role) || toOpt(role)) : null} onChange={({ detail }) => onRole(detail.selectedOption.value)}
          placeholder="Choose an IAM role" options={ropts} statusType={roles.loading ? "loading" : "finished"} empty="No IAM role trusts rds.amazonaws.com" ariaLabel="IAM role" />
      </FormField>
    </SpaceBetween>
  );
}

export function IamRolesPanel({ d, reload }) {
  const notify = useNotify();
  const [adding, setAdding] = useState(false);
  const [role, setRole] = useState("");
  const [feature, setFeature] = useState("");
  const [busy, setBusy] = useState(false);
  const roles = (() => { const r = d.AssociatedRoles?.DBInstanceRole; return r ? [].concat(r) : []; })();
  const add = async () => {
    setBusy(true);
    try { await api.addRoleToDBInstance(d.DBInstanceIdentifier, role, feature); notify.success("IAM role associated."); setAdding(false); setRole(""); setFeature(""); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  const remove = async (r) => { try { await api.removeRoleFromDBInstance(d.DBInstanceIdentifier, r.RoleArn, r.FeatureName); notify.success("IAM role removed."); reload(); } catch (e) { notify.error(e); } };
  return (
    <>
      <Table variant="container" items={roles} trackBy="RoleArn"
        header={<Header variant="h2" counter={`(${roles.length})`} actions={<Button onClick={() => setAdding(true)}>Add IAM role</Button>}>Manage IAM roles</Header>}
        columnDefinitions={[
          { id: "r", header: "IAM role", cell: (r) => r.RoleArn.split("/").pop() },
          { id: "f", header: "Feature", cell: (r) => r.FeatureName },
          { id: "s", header: "Status", cell: (r) => <StatusIndicator type="success">{r.Status}</StatusIndicator> },
          { id: "a", header: "", cell: (r) => <Button variant="inline-link" onClick={() => remove(r)}>Delete</Button> },
        ]} empty={<Box textAlign="center" color="inherit"><b>No IAM roles</b></Box>} />
      <Modal visible={adding} onDismiss={() => setAdding(false)} header="Add IAM role to this instance"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setAdding(false)}>Cancel</Button><Button variant="primary" loading={busy} disabled={!role || !feature} onClick={add}>Add role</Button></SpaceBetween></Box>}>
        <RolePicker role={role} feature={feature} onRole={setRole} onFeature={setFeature} />
      </Modal>
    </>
  );
}

const METRICS = ["CPUUtilization", "DatabaseConnections", "ReadIOPS", "WriteIOPS", "FreeStorageSpace", "FreeableMemory"];
const COMPARISONS = [["GreaterThanThreshold", ">"], ["GreaterThanOrEqualToThreshold", ">="], ["LessThanThreshold", "<"], ["LessThanOrEqualToThreshold", "<="]];

export function AlarmsPanel({ id }) {
  const notify = useNotify();
  const alarms = useAsync(() => api.describeDbAlarms(id), [id]);
  const topics = useAsync(() => api.listSnsTopicArns(), []);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", metric: "DatabaseConnections", comparison: "GreaterThanThreshold", threshold: "10", topic: "" });
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await api.putDbAlarm(id, { name: f.name, metric: f.metric, threshold: f.threshold, comparison: f.comparison, actions: f.topic ? [f.topic] : [] });
      notify.success(`Alarm ${f.name} created.`); setOpen(false); alarms.reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <>
      <Table variant="container" loading={alarms.loading} items={alarms.data || []} trackBy="AlarmName"
        header={<Header variant="h2" counter={`(${(alarms.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh alarms" onClick={alarms.reload} />
          <Button variant="primary" onClick={() => { setF({ ...f, name: `${id}-alarm` }); setOpen(true); }}>Create CloudWatch alarm</Button></SpaceBetween>}>CloudWatch alarms</Header>}
        columnDefinitions={[
          { id: "n", header: "Alarm", cell: (a) => <a href={`#/cloudwatch/alarms/${a.AlarmName}`}>{a.AlarmName}</a> },
          { id: "s", header: "State", cell: (a) => <StatusIndicator type={a.StateValue === "OK" ? "success" : a.StateValue === "ALARM" ? "error" : "pending"}>{a.StateValue}</StatusIndicator> },
          { id: "m", header: "Condition", cell: (a) => `${a.MetricName} ${(COMPARISONS.find((c) => c[0] === a.ComparisonOperator) || [0, a.ComparisonOperator])[1]} ${a.Threshold}` },
          { id: "x", header: "", cell: (a) => <Button variant="inline-link" onClick={async () => { await api.deleteAlarms([a.AlarmName]); alarms.reload(); }}>Delete</Button> },
        ]} empty={<Box textAlign="center" color="inherit"><b>No alarms on this DB instance</b></Box>} />
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Create CloudWatch alarm"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={busy} disabled={!f.name} onClick={create}>Create alarm</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m">
          <FormField label="Alarm name"><Input ariaLabel="Alarm name" value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} /></FormField>
          <FormField label="Metric"><Select ariaLabel="Metric" selectedOption={toOpt(f.metric)} options={METRICS.map(toOpt)} onChange={({ detail }) => setF({ ...f, metric: detail.selectedOption.value })} /></FormField>
          <FormField label="Condition"><Select ariaLabel="Condition" selectedOption={{ value: f.comparison, label: (COMPARISONS.find((c) => c[0] === f.comparison) || [])[1] }} options={COMPARISONS.map(([v, l]) => ({ value: v, label: l }))} onChange={({ detail }) => setF({ ...f, comparison: detail.selectedOption.value })} /></FormField>
          <FormField label="Threshold"><Input ariaLabel="Threshold" type="number" value={f.threshold} onChange={({ detail }) => setF({ ...f, threshold: detail.value })} /></FormField>
          <FormField label="Notify (SNS topic) - optional"><Select ariaLabel="SNS topic" selectedOption={f.topic ? toOpt(f.topic) : null} placeholder="No notification" options={(topics.data || []).map(toOpt)} onChange={({ detail }) => setF({ ...f, topic: detail.selectedOption.value })} /></FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
}

export function ServiceQuota() {
  const q = useAsync(() => api.describeAccountQuotas(), []);
  return (
    <ContentLayout header={<Header variant="h1" description="Default Amazon RDS quotas for this account and Region, with live usage.">Service quotas</Header>}>
      <Table variant="container" loading={q.loading} items={q.data || []} trackBy="name"
        header={<Header variant="h2" counter={`(${(q.data || []).length})`} actions={<Button iconName="refresh" ariaLabel="Refresh quotas" onClick={q.reload} />}>Quotas</Header>}
        columnDefinitions={[
          { id: "n", header: "Quota name", cell: (x) => x.name },
          { id: "u", header: "Used", cell: (x) => x.used },
          { id: "m", header: "Quota value", cell: (x) => x.max },
          { id: "p", header: "Utilization", cell: (x) => <ProgressBar value={Math.min(100, (x.used / x.max) * 100)} variant="standalone" /> },
        ]} />
    </ContentLayout>
  );
}
