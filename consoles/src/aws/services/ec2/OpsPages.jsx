/* AWS-03 / AWS-04 EC2 pages backed by real engines (core/ec2_ops_core.py, core/iam_core.py instance profiles,
 * the native `rbin` REST service): Events, Recycle Bin, Create IAM profile, Compare security group rules,
 * Instance type finder, Spot requests, Reserved Instances, Capacity Reservations, Dedicated Hosts, plus the
 * account-wide health rollup, EBS fault-tolerance widget, Managed resources + Auto Scaling settings tabs. */
import { useMemo, useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Multiselect from "@cloudscape-design/components/multiselect";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ProgressBar from "@cloudscape-design/components/progress-bar";
import Alert from "@cloudscape-design/components/alert";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { CapabilityBadge, CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

const opt = (v, label) => ({ value: String(v), label: label ?? String(v) });
const page = (title, badge, children, actions) => (
  <ContentLayout header={<Header variant="h1" actions={actions || (badge ? <CapabilityBadge id={badge} /> : undefined)}>{title}</Header>}>{children}</ContentLayout>
);

/** Modal with a submit button that surfaces API errors inline. */
function FormModal({ visible, title, submit, onDismiss, onSubmit, children, disabled }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => { setBusy(true); setError(null); try { await onSubmit(); onDismiss(); } catch (e) { setError(e); } finally { setBusy(false); } };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={title}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={disabled} onClick={go}>{submit}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">{error && <ErrorAlert error={error} />}{children}</SpaceBetween>
    </Modal>
  );
}

const toIso = (s) => { const d = new Date(s); return isNaN(d) ? s : d.toISOString().replace(/\.\d+Z$/, "Z"); };
const inDays = (n) => new Date(Date.now() + n * 86400e3).toISOString().replace(/\.\d+Z$/, "Z");

// ── Events ───────────────────────────────────────────────────────────────────────────────────
export function Events() {
  const notify = useNotify();
  const t = useAsync(() => api.describeInstanceStatusAll(), []);
  const events = (t.data || []).flatMap((s) => s.events.map((e) => ({ ...e, state: s.state })));
  const insts = (t.data || []).filter((s) => s.state !== "terminated");
  const [sel, setSel] = useState([]);
  const [sched, setSched] = useState(false);
  const [resched, setResched] = useState(false);
  const [f, setF] = useState({ instance: "", code: "system-reboot", when: inDays(3), description: "" });
  return page("Events", "ec2.events", <>
    <ResourceTable resourceName="Scheduled events" items={events} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="id"
      selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter scheduled events"
      empty={{ title: "No scheduled events", subtitle: "None of your instances have a scheduled maintenance event." }}
      columns={[
        { id: "id", header: "Event ID", isRowHeader: true, cell: (e) => e.id },
        { id: "inst", header: "Resource ID", cell: (e) => <a href={href("ec2", "instances", e.instanceId)} onClick={follow}>{e.instanceId}</a> },
        { id: "code", header: "Event type", cell: (e) => e.code },
        { id: "status", header: "Event status", cell: (e) => (/^\[Completed\]/.test(e.description) ? <StatusIndicator type="success">Completed</StatusIndicator> : <StatusIndicator type="pending">Scheduled</StatusIndicator>) },
        { id: "desc", header: "Description", cell: (e) => e.description },
        { id: "start", header: "Start time", cell: (e) => fmtDate(e.notBefore) },
        { id: "end", header: "End time", cell: (e) => fmtDate(e.notAfter) },
        { id: "deadline", header: "Deadline", cell: (e) => fmtDate(e.deadline) },
      ]}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1 || /^\[Completed\]/.test(sel[0]?.description || "")} onClick={() => { setF({ ...f, when: inDays(4) }); setResched(true); }}>Reschedule event</Button>
        <Button variant="primary" disabled={!insts.length} onClick={() => { setF({ ...f, instance: insts[0].instanceId }); setSched(true); }}>Schedule test event</Button>
      </SpaceBetween>} />
    <FormModal visible={sched} title="Schedule a test event" submit="Schedule" onDismiss={() => setSched(false)}
      onSubmit={async () => { await api.scheduleInstanceEvent({ InstanceId: f.instance, Code: f.code, NotBefore: toIso(f.when), Description: f.description || f.code }); notify.success("Event scheduled."); t.reload(); }}>
      <Alert type="info">AWS raises maintenance events itself; Vyomi has no hardware to retire, so this simulator-only action stands in for it. A due instance-stop / instance-retirement event really stops the instance.</Alert>
      <FormField label="Instance"><Select selectedOption={f.instance ? opt(f.instance) : null} onChange={({ detail }) => setF({ ...f, instance: detail.selectedOption.value })} options={insts.map((i) => opt(i.instanceId))} ariaLabel="Instance" /></FormField>
      <FormField label="Event type"><Select selectedOption={opt(f.code)} onChange={({ detail }) => setF({ ...f, code: detail.selectedOption.value })} options={["instance-reboot", "system-reboot", "system-maintenance", "instance-retirement", "instance-stop"].map((c) => opt(c))} ariaLabel="Event type" /></FormField>
      <FormField label="Start time (UTC, ISO-8601)"><Input value={f.when} onChange={({ detail }) => setF({ ...f, when: detail.value })} ariaLabel="Start time" /></FormField>
      <FormField label="Description"><Input value={f.description} onChange={({ detail }) => setF({ ...f, description: detail.value })} ariaLabel="Description" /></FormField>
    </FormModal>
    <FormModal visible={resched} title="Reschedule event" submit="Reschedule" onDismiss={() => setResched(false)}
      onSubmit={async () => { await api.modifyInstanceEventStartTime(sel[0].instanceId, sel[0].id, toIso(f.when)); notify.success("Event rescheduled."); setSel([]); t.reload(); }}>
      <FormField label="New start time (UTC, ISO-8601)" description="Must be in the future and before the event deadline."><Input value={f.when} onChange={({ detail }) => setF({ ...f, when: detail.value })} ariaLabel="New start time" /></FormField>
    </FormModal>
  </>);
}

// ── Account-wide instance health rollup (Instances page) ─────────────────────────────────────
export function HealthRollup() {
  const t = useAsync(() => api.describeInstanceStatusAll(), []);
  const rows = t.data || [];
  const live = rows.filter((r) => r.state === "running");
  const cnt = (fn) => live.filter(fn).length;
  const failed = cnt((r) => r.systemStatus === "impaired" || r.instanceStatus === "impaired");
  const initial = cnt((r) => r.systemStatus === "initializing" || r.instanceStatus === "initializing");
  const events = rows.reduce((n, r) => n + r.events.filter((e) => !/^\[Completed\]/.test(e.description)).length, 0);
  const cell = (label, value, type) => <div key={label}><Box variant="awsui-key-label">{label}</Box><StatusIndicator type={type}>{value}</StatusIndicator></div>;
  return (
    <Container header={<Header variant="h2" description="Computed live from DescribeInstanceStatus across every instance in this Region." actions={<><Button iconName="refresh" ariaLabel="Refresh health" onClick={t.reload} /><CapabilityBadge id="ec2.health-rollup" /></>}>Instance health</Header>}>
      {t.error ? <ErrorAlert error={t.error} /> : (
        <ColumnLayout columns={5} variant="text-grid" data-testid="health-rollup">
          {cell("Running instances", live.length, "info")}
          {cell("Passing 2/2 checks", cnt((r) => r.systemStatus === "ok" && r.instanceStatus === "ok"), "success")}
          {cell("Impaired", failed, failed ? "error" : "success")}
          {cell("Initializing", initial, initial ? "in-progress" : "success")}
          {cell("Scheduled events", events, events ? "warning" : "success")}
        </ColumnLayout>
      )}
    </Container>
  );
}

// ── EBS fault tolerance (Volumes page) ───────────────────────────────────────────────────────
export function FaultTolerance() {
  const t = useAsync(() => Promise.all([api.describeVolumes(), api.describeSnapshots()]), []);
  const [vols, snaps] = t.data || [[], []];
  const now = Date.now();
  const latest = {};
  snaps.forEach((s) => { const ts = Date.parse(s.startTime); if (!latest[s.volumeId] || ts > latest[s.volumeId]) latest[s.volumeId] = ts; });
  const none = vols.filter((v) => !latest[v.volumeId]);
  const stale = vols.filter((v) => latest[v.volumeId] && now - latest[v.volumeId] > 7 * 86400e3);
  const recent = vols.length - none.length - stale.length;
  const pct = vols.length ? Math.round((recent / vols.length) * 100) : 100;
  return (
    <Container header={<Header variant="h2" description="Snapshot coverage across every volume in this Region (a recent snapshot is one taken in the last 7 days)." actions={<CapabilityBadge id="ec2.volumes.fault-tolerance" />}>Fault tolerance for all volumes in this Region</Header>}>
      {t.error ? <ErrorAlert error={t.error} /> : (
        <SpaceBetween size="s">
          <ProgressBar value={pct} label="Volumes with a recent snapshot" description={`${recent} of ${vols.length} volumes`} status={t.loading ? "in-progress" : undefined} resultText="" />
          <ColumnLayout columns={3} variant="text-grid" data-testid="fault-tolerance">
            <div><Box variant="awsui-key-label">With a recent snapshot</Box><StatusIndicator type="success">{recent}</StatusIndicator></div>
            <div><Box variant="awsui-key-label">Latest snapshot older than 7 days</Box><StatusIndicator type={stale.length ? "warning" : "success"}>{stale.length}</StatusIndicator></div>
            <div><Box variant="awsui-key-label">No snapshot</Box><StatusIndicator type={none.length ? "error" : "success"}>{none.length}</StatusIndicator></div>
          </ColumnLayout>
          {none.length > 0 && <Box variant="small">Not backed up: {none.slice(0, 5).map((v) => v.volumeId).join(", ")}{none.length > 5 ? "…" : ""}</Box>}
        </SpaceBetween>
      )}
    </Container>
  );
}

// ── Dashboard widgets ────────────────────────────────────────────────────────────────────────
export function ZonesWidget() {
  const t = useAsync(() => api.describeZones(true), []);
  const zones = t.data || [];
  return (
    <Container header={<Header variant="h2" actions={<Button href={href("ec2", "settings")} onFollow={follow}>Manage zones</Button>}>Zones</Header>}>
      {t.error ? <ErrorAlert error={t.error} /> : (
        <Table variant="embedded" loading={t.loading} items={zones} trackBy="zoneName" columnDefinitions={[
          { id: "n", header: "Zone name", cell: (z) => z.zoneName }, { id: "i", header: "Zone ID", cell: (z) => z.zoneId },
          { id: "t", header: "Type", cell: (z) => z.zoneType }, { id: "o", header: "Opt-in status", cell: (z) => z.optInStatus },
        ]} empty="No zones" />
      )}
    </Container>
  );
}

export function AlarmsWidget() {
  const t = useAsync(() => api.describeEc2Alarms(), []);
  const alarms = t.data || [];
  const by = (s) => alarms.filter((a) => a.StateValue === s).length;
  return (
    <Container header={<Header variant="h2" description="CloudWatch alarms in the AWS/EC2 namespace." actions={<CapabilityBadge id="ec2.instances.alarms-metrics" />}>Instance alarms</Header>}>
      {t.error ? <ErrorAlert error={t.error} /> : (
        <SpaceBetween size="s">
          <ColumnLayout columns={3} variant="text-grid" data-testid="alarms-widget">
            <div><Box variant="awsui-key-label">In alarm</Box><StatusIndicator type={by("ALARM") ? "error" : "success"}>{by("ALARM")}</StatusIndicator></div>
            <div><Box variant="awsui-key-label">Insufficient data</Box><StatusIndicator type="pending">{by("INSUFFICIENT_DATA")}</StatusIndicator></div>
            <div><Box variant="awsui-key-label">OK</Box><StatusIndicator type="success">{by("OK")}</StatusIndicator></div>
          </ColumnLayout>
          {alarms.length === 0 && !t.loading && <Box color="text-body-secondary">No EC2 alarms. Create one from an instance's Monitoring tab.</Box>}
        </SpaceBetween>
      )}
    </Container>
  );
}

// ── Recycle Bin ──────────────────────────────────────────────────────────────────────────────
const RB_TYPES = { EBS_SNAPSHOT: "EBS snapshots", EC2_IMAGE: "AMIs" };
export function RecycleBin() {
  const notify = useNotify();
  const rules = useAsync(async () => (await Promise.all(Object.keys(RB_TYPES).map(async (type) => (await api.listRetentionRules(type)).map((r) => ({ ...r, type }))))).flat(), []);
  const res = useAsync(async () => [
    ...(await api.listSnapshotsInBin()).map((s) => ({ id: s.snapshotId, kind: "Snapshot", detail: s.volumeId, enter: s.recycleBinEnterTime, exit: s.recycleBinExitTime })),
    ...(await api.listImagesInBin()).map((i) => ({ id: i.imageId, kind: "AMI", detail: i.name, enter: i.recycleBinEnterTime, exit: i.recycleBinExitTime }))], []);
  const [sel, setSel] = useState([]);
  const [rsel, setRsel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [lockM, setLockM] = useState(false);
  const [f, setF] = useState({ type: "EBS_SNAPSHOT", days: "7", desc: "", tagKey: "", tagValue: "", lockDays: "7" });
  const rule = sel[0];
  const locked = rule && rule.LockState !== "unlocked";
  const run = async (fn, ok) => { try { await fn(); notify.success(ok); setSel([]); rules.reload(); } catch (e) { notify.error(e); } };
  return page("Recycle Bin", "ec2.recycle-bin", <>
    <Tabs tabs={[
      { id: "rules", label: "Retention rules", content: (
        <ResourceTable resourceName="Retention rules" items={rules.data || []} loading={rules.loading} error={rules.error} onRefresh={rules.reload} trackBy="Identifier"
          selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter retention rules"
          empty={{ title: "No retention rules", subtitle: "Create a rule so deleted snapshots and AMIs are retained and recoverable." }}
          columns={[
            { id: "id", header: "Rule ID", isRowHeader: true, cell: (r) => r.Identifier },
            { id: "type", header: "Resource type", cell: (r) => RB_TYPES[r.type] },
            { id: "desc", header: "Description", cell: (r) => r.Description || "-" },
            { id: "ret", header: "Retention period", cell: (r) => `${r.RetentionPeriod.RetentionPeriodValue} days` },
            { id: "lock", header: "Lock state", cell: (r) => r.LockState },
            { id: "end", header: "Unlock time", cell: (r) => (r.LockEndTime ? fmtDate(r.LockEndTime * 1000) : "-") },
          ]}
          actions={<SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!rule} items={[
              { id: "lock", text: "Lock rule", disabled: locked }, { id: "unlock", text: "Unlock rule", disabled: rule?.LockState !== "locked" }, { id: "delete", text: "Delete rule", disabled: locked }]}
              onItemClick={({ detail }) => {
                if (detail.id === "lock") setLockM(true);
                else if (detail.id === "delete") setDel(true);
                else run(() => api.unlockRetentionRule(rule.Identifier), "Rule is pending unlock; it unlocks once its unlock delay passes.");
              }}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreate(true)}>Create retention rule</Button>
          </SpaceBetween>} />) },
      { id: "res", label: "Resources", content: (
        <ResourceTable resourceName="Resources in the Recycle Bin" items={res.data || []} loading={res.loading} error={res.error} onRefresh={res.reload} trackBy="id"
          selectionType="single" selectedItems={rsel} onSelectionChange={setRsel} filterPlaceholder="Filter resources"
          empty={{ title: "The Recycle Bin is empty", subtitle: "Deleted snapshots and AMIs that match a retention rule appear here." }}
          columns={[
            { id: "id", header: "Resource ID", isRowHeader: true, cell: (r) => r.id }, { id: "kind", header: "Type", cell: (r) => r.kind },
            { id: "d", header: "Volume / name", cell: (r) => r.detail || "-" },
            { id: "e", header: "Deleted", cell: (r) => fmtDate(r.enter) }, { id: "x", header: "Retained until", cell: (r) => fmtDate(r.exit) },
          ]}
          actions={<Button disabled={rsel.length !== 1} onClick={async () => {
            try { await (rsel[0].kind === "Snapshot" ? api.restoreSnapshotFromBin(rsel[0].id) : api.restoreImageFromBin(rsel[0].id)); notify.success(`${rsel[0].id} recovered.`); setRsel([]); res.reload(); } catch (e) { notify.error(e); }
          }}>Recover</Button>} />) },
    ]} />
    <FormModal visible={create} title="Create retention rule" submit="Create retention rule" onDismiss={() => setCreate(false)} disabled={!f.days}
      onSubmit={async () => {
        await api.createRetentionRule({ ResourceType: f.type, Description: f.desc || undefined, RetentionPeriod: { RetentionPeriodValue: Number(f.days), RetentionPeriodUnit: "DAYS" },
          ResourceTags: f.tagKey ? [{ ResourceTagKey: f.tagKey, ResourceTagValue: f.tagValue || undefined }] : undefined });
        notify.success("Retention rule created."); rules.reload(); res.reload();
      }}>
      <FormField label="Resource type"><RadioGroup value={f.type} onChange={({ detail }) => setF({ ...f, type: detail.value })} items={Object.entries(RB_TYPES).map(([value, label]) => ({ value, label }))} /></FormField>
      <FormField label="Retention period (days)"><Input value={f.days} type="number" onChange={({ detail }) => setF({ ...f, days: detail.value })} ariaLabel="Retention period in days" /></FormField>
      <FormField label="Description"><Input value={f.desc} onChange={({ detail }) => setF({ ...f, desc: detail.value })} ariaLabel="Rule description" /></FormField>
      <FormField label="Tag key (optional)" description="Leave empty for a Region-level rule that retains every deleted resource of this type."><Input value={f.tagKey} onChange={({ detail }) => setF({ ...f, tagKey: detail.value })} ariaLabel="Resource tag key" /></FormField>
      {f.tagKey && <FormField label="Tag value"><Input value={f.tagValue} onChange={({ detail }) => setF({ ...f, tagValue: detail.value })} ariaLabel="Resource tag value" /></FormField>}
    </FormModal>
    <FormModal visible={lockM} title="Lock retention rule" submit="Lock rule" onDismiss={() => setLockM(false)}
      onSubmit={async () => { await api.lockRetentionRule(rule.Identifier, Number(f.lockDays)); notify.success("Rule locked."); setSel([]); rules.reload(); }}>
      <FormField label="Unlock delay (days, 7-30)" description="A locked rule can't be changed or deleted until it has been unlocked and the delay has passed."><Input value={f.lockDays} type="number" onChange={({ detail }) => setF({ ...f, lockDays: detail.value })} ariaLabel="Unlock delay in days" /></FormField>
    </FormModal>
    <DeleteModal visible={del} resourceType="retention rule" names={sel.map((r) => r.Identifier)} confirmText="delete" onDismiss={() => setDel(false)}
      onConfirm={async () => { await api.deleteRetentionRule(rule.Identifier); notify.success("Retention rule deleted."); setSel([]); rules.reload(); }} />
  </>);
}

// ── Create IAM profile ───────────────────────────────────────────────────────────────────────
const EC2_TRUST = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: "ec2.amazonaws.com" }, Action: "sts:AssumeRole" }] });
export function CreateIamProfile() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [mode, setMode] = useState("new");
  const [roleName, setRoleName] = useState("");
  const [existing, setExisting] = useState(null);
  const [policies, setPolicies] = useState([]);
  const roles = useAsync(() => api.iamListRoles(), []);
  const pols = useAsync(() => api.iamListPolicies(), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      let role = existing?.value;
      if (mode === "new") {
        role = roleName || `${name}-role`;
        await api.iamCreateRole(role, EC2_TRUST);
        for (const p of policies) await api.iamAttachRolePolicy(role, p.value);
      }
      await api.createInstanceProfile(name);
      if (role) await api.addRoleToInstanceProfile(name, role);
      notify.success(`Instance profile "${name}" created.`);
      navigate("ec2", "launch-instance");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return page("Create IAM profile", "ec2.iam-instance-profiles", (
    <Form errorText={error && <ErrorAlert error={error} />} actions={<SpaceBetween direction="horizontal" size="xs">
      <Button formAction="none" href={href("ec2", "launch-instance")} onFollow={follow}>Cancel</Button>
      <Button variant="primary" loading={busy} disabled={!name || (mode === "existing" && !existing)} onClick={submit}>Create instance profile</Button></SpaceBetween>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Instance profile</Header>}>
          <FormField label="Instance profile name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Instance profile name" /></FormField>
        </Container>
        <Container header={<Header variant="h2">Role</Header>}>
          <SpaceBetween size="l">
            <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)} items={[{ value: "new", label: "Create a new role for EC2" }, { value: "existing", label: "Use an existing role" }, { value: "none", label: "No role (empty profile)" }]} />
            {mode === "new" && <>
              <FormField label="Role name" description={`Defaults to "${name || "<profile>"}-role". Trusts ec2.amazonaws.com.`}><Input value={roleName} onChange={({ detail }) => setRoleName(detail.value)} ariaLabel="Role name" /></FormField>
              <FormField label="Managed policies to attach"><Multiselect selectedOptions={policies} onChange={({ detail }) => setPolicies(detail.selectedOptions)} filteringType="auto" placeholder="Choose policies" ariaLabel="Managed policies"
                options={(pols.data || []).map((p) => ({ value: p.Arn, label: p.PolicyName }))} statusType={pols.loading ? "loading" : "finished"} /></FormField></>}
            {mode === "existing" && <FormField label="Role"><Select selectedOption={existing} onChange={({ detail }) => setExisting(detail.selectedOption)} placeholder="Choose a role" ariaLabel="Existing role"
              options={(roles.data || []).map((r) => ({ value: r.RoleName, label: r.RoleName }))} statusType={roles.loading ? "loading" : "finished"} /></FormField>}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </Form>
  ));
}

// ── Compare security group rules ─────────────────────────────────────────────────────────────
const ruleKey = (dir, p, src) => `${dir}|${p.IpProtocol}|${p.FromPort ?? "all"}-${p.ToPort ?? "all"}|${src}`;
export function CompareSecurityGroupRules() {
  const sgs = useAsync(() => api.describeSecurityGroups(), []);
  const [picked, setPicked] = useState([]);
  const [onlyDiff, setOnlyDiff] = useState(false);
  const chosen = (sgs.data || []).filter((g) => picked.some((p) => p.value === g.GroupId));
  const matrix = useMemo(() => {
    const m = new Map();
    chosen.forEach((g) => {
      [["Inbound", g.IpPermissions], ["Outbound", g.IpPermissionsEgress]].forEach(([dir, perms]) => perms.forEach((p) => {
        [...p.cidrs, ...p.groupIds].forEach((src) => {
          const k = ruleKey(dir, p, src);
          if (!m.has(k)) m.set(k, { key: k, dir, proto: p.IpProtocol === "-1" ? "All" : p.IpProtocol, ports: p.FromPort === undefined ? "All" : p.FromPort === p.ToPort ? String(p.FromPort) : `${p.FromPort}-${p.ToPort}`, src, in: new Set() });
          m.get(k).in.add(g.GroupId);
        });
      }));
    });
    return [...m.values()].sort((a, b) => a.key.localeCompare(b.key));
  }, [chosen.map((g) => g.GroupId).join(",")]);  // eslint-disable-line
  const rows = onlyDiff ? matrix.filter((r) => r.in.size !== chosen.length) : matrix;
  return page("Compare security group rules", "ec2.compare-sg-rules", (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" description="Pick two or more security groups; every rule is lined up across them.">Security groups</Header>}>
        <SpaceBetween size="m">
          <Multiselect selectedOptions={picked} onChange={({ detail }) => setPicked(detail.selectedOptions.slice(0, 5))} filteringType="auto" placeholder="Choose security groups to compare" ariaLabel="Security groups to compare"
            options={(sgs.data || []).map((g) => ({ value: g.GroupId, label: `${g.GroupName} (${g.GroupId})`, description: g.VpcId }))} statusType={sgs.loading ? "loading" : "finished"} />
          <Button onClick={() => setOnlyDiff(!onlyDiff)} pressed={onlyDiff} iconName={onlyDiff ? "check" : undefined}>Show only differences</Button>
        </SpaceBetween>
      </Container>
      {chosen.length >= 2 && (
        <Table variant="container" data-testid="sg-compare" header={<Header variant="h2" counter={`(${rows.length})`}>Rules</Header>} items={rows} trackBy="key"
          empty={<Box textAlign="center">{onlyDiff ? "The selected groups have identical rules." : "These groups have no rules."}</Box>}
          columnDefinitions={[
            { id: "dir", header: "Direction", cell: (r) => r.dir }, { id: "proto", header: "Protocol", cell: (r) => r.proto },
            { id: "ports", header: "Port range", cell: (r) => r.ports }, { id: "src", header: "Source / destination", cell: (r) => r.src },
            ...chosen.map((g) => ({ id: g.GroupId, header: g.GroupName, cell: (r) => (r.in.has(g.GroupId) ? <StatusIndicator type="success">Present</StatusIndicator> : <StatusIndicator type="stopped">Missing</StatusIndicator>) })),
            { id: "diff", header: "Result", cell: (r) => (r.in.size === chosen.length ? "Same" : <StatusIndicator type="warning">Different</StatusIndicator>) },
          ]} />
      )}
      {chosen.length < 2 && <Box color="text-body-secondary">Select at least two security groups.</Box>}
    </SpaceBetween>
  ));
}

// ── Instance type finder ─────────────────────────────────────────────────────────────────────
const WORKLOADS = { general: ["t3", "t3a", "t4g", "m5", "m6i"], compute: ["c5", "c6i"], memory: ["r5", "r6i"], burstable: ["t2", "t3", "t3a", "t4g"] };
export function InstanceTypeFinder() {
  const t = useAsync(() => api.describeInstanceTypes(), []);
  const [w, setW] = useState("general");
  const [arch, setArch] = useState("any");
  const [minCpu, setMinCpu] = useState("1");
  const [minMem, setMinMem] = useState("1");
  const [free, setFree] = useState(false);
  const fam = (x) => x.InstanceType.split(".")[0];
  const rows = (t.data || []).filter((x) => (WORKLOADS[w] ? WORKLOADS[w].includes(fam(x)) || (w === "general" && !["c", "r"].includes(fam(x)[0])) : true)
    && (arch === "any" || x.Architectures.includes(arch)) && x.VCpuCount >= Number(minCpu || 0) && x.MemoryMiB / 1024 >= Number(minMem || 0) && (!free || x.FreeTierEligible))
    .map((x) => ({ ...x, id: x.InstanceType, mem: x.MemoryMiB / 1024 })).sort((a, b) => a.VCpuCount - b.VCpuCount || a.mem - b.mem);
  return page("Instance type finder", "ec2.instance-type-finder", (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" description="Describe the workload; matching types come from the live DescribeInstanceTypes catalog.">Requirements</Header>}>
        <ColumnLayout columns={4}>
          <FormField label="Workload"><Select selectedOption={opt(w, { general: "General purpose", compute: "Compute optimized", memory: "Memory optimized", burstable: "Burstable (T family)" }[w])} onChange={({ detail }) => setW(detail.selectedOption.value)} ariaLabel="Workload"
            options={[["general", "General purpose"], ["compute", "Compute optimized"], ["memory", "Memory optimized"], ["burstable", "Burstable (T family)"]].map(([v, l]) => opt(v, l))} /></FormField>
          <FormField label="Architecture"><Select selectedOption={opt(arch)} onChange={({ detail }) => setArch(detail.selectedOption.value)} ariaLabel="Architecture" options={["any", "x86_64", "arm64"].map((v) => opt(v))} /></FormField>
          <FormField label="Minimum vCPUs"><Input type="number" value={minCpu} onChange={({ detail }) => setMinCpu(detail.value)} ariaLabel="Minimum vCPUs" /></FormField>
          <FormField label="Minimum memory (GiB)"><Input type="number" value={minMem} onChange={({ detail }) => setMinMem(detail.value)} ariaLabel="Minimum memory GiB" /></FormField>
        </ColumnLayout>
        <Box margin={{ top: "s" }}><Button pressed={free} onClick={() => setFree(!free)}>Free tier eligible only</Button></Box>
      </Container>
      <ResourceTable resourceName="Matching instance types" items={rows} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="id" filterPlaceholder="Filter matches"
        empty={{ title: "No instance type matches", subtitle: "Relax a requirement." }}
        columns={[
          { id: "t", header: "Instance type", isRowHeader: true, cell: (x) => <a href={href("ec2", "instance-types", x.InstanceType)} onClick={follow}>{x.InstanceType}</a>, sortingField: "InstanceType" },
          { id: "v", header: "vCPUs", cell: (x) => x.VCpuCount }, { id: "m", header: "Memory (GiB)", cell: (x) => x.mem },
          { id: "a", header: "Architecture", cell: (x) => x.Architectures.join(", ") }, { id: "n", header: "Network", cell: (x) => x.NetworkPerformance },
          { id: "f", header: "Free tier", cell: (x) => (x.FreeTierEligible ? "Yes" : "No") },
          { id: "go", header: "Launch", cell: (x) => <a href={href("ec2", "launch-instance")} onClick={follow}>Launch</a> },
        ]} />
    </SpaceBetween>
  ));
}

// ── Spot requests ────────────────────────────────────────────────────────────────────────────
const stateType = (s) => ({ active: "success", open: "pending", closed: "stopped", cancelled: "stopped", failed: "error", available: "success", released: "stopped", expired: "stopped", retired: "stopped" }[s] || "info");
export function SpotRequests() {
  const notify = useNotify();
  const t = useAsync(() => api.describeSpotRequests(), []);
  const amis = useAsync(() => api.describeImages({ Owner: ["amazon"] }).catch(() => []), []);
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ image: "", type: "t3.micro", price: "", persistent: false, count: "1" });
  const ph = useAsync(() => api.describeSpotPriceHistory([f.type], undefined).then((xs) => xs.slice(0, 3)), [f.type]);
  const imgs = (amis.data || []).slice(0, 25);
  const image = f.image || imgs[0]?.imageId || "";
  return page("Spot Requests", "ec2.purchasing.spot", <SpaceBetween size="l">
    <ResourceTable resourceName="Spot requests" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="spotInstanceRequestId"
      selectionType="multi" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter Spot requests"
      empty={{ title: "No Spot requests", subtitle: "Request Spot capacity at a maximum price." }}
      columns={[
        { id: "id", header: "Request ID", isRowHeader: true, cell: (r) => r.spotInstanceRequestId },
        { id: "type", header: "Request type", cell: (r) => r.type },
        { id: "state", header: "Request state", cell: (r) => <StatusIndicator type={stateType(r.state)}>{r.state}</StatusIndicator> },
        { id: "status", header: "Status", cell: (r) => r.status?.code },
        { id: "inst", header: "Instance ID", cell: (r) => (r.instanceId ? <a href={href("ec2", "instances", r.instanceId)} onClick={follow}>{r.instanceId}</a> : "-") },
        { id: "it", header: "Instance type", cell: (r) => r.launchSpecification?.instanceType },
        { id: "max", header: "Max price (USD/hr)", cell: (r) => r.spotPrice },
        { id: "az", header: "Availability Zone", cell: (r) => r.launchedAvailabilityZone || "-" },
        { id: "ct", header: "Created", cell: (r) => fmtDate(r.createTime) },
      ]}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => { try { await api.cancelSpotRequests(sel.map((r) => r.spotInstanceRequestId)); notify.success("Spot request(s) cancelled."); setSel([]); t.reload(); } catch (e) { notify.error(e); } }}>Cancel request</Button>
        <Button variant="primary" onClick={() => setOpen(true)}>Request Spot Instances</Button>
      </SpaceBetween>} />
    <FormModal visible={open} title="Request Spot Instances" submit="Request" onDismiss={() => setOpen(false)} disabled={!image}
      onSubmit={async () => { await api.requestSpotInstances({ SpotPrice: f.price || undefined, InstanceCount: Number(f.count), Type: f.persistent ? "persistent" : "one-time", LaunchSpecification: { ImageId: image, InstanceType: f.type } }); notify.success("Spot request submitted."); t.reload(); }}>
      <FormField label="AMI"><Select selectedOption={image ? opt(image) : null} onChange={({ detail }) => setF({ ...f, image: detail.selectedOption.value })} options={imgs.map((i) => opt(i.imageId, `${i.imageId} - ${i.name}`))} ariaLabel="AMI" /></FormField>
      <FormField label="Instance type"><Input value={f.type} onChange={({ detail }) => setF({ ...f, type: detail.value })} ariaLabel="Instance type" /></FormField>
      <FormField label="Maximum price (USD/hour)" description="Defaults to the on-demand price. A request below the current Spot price stays open until the price drops."><Input value={f.price} onChange={({ detail }) => setF({ ...f, price: detail.value })} ariaLabel="Maximum price" /></FormField>
      <FormField label="Count"><Input type="number" value={f.count} onChange={({ detail }) => setF({ ...f, count: detail.value })} ariaLabel="Instance count" /></FormField>
      <Button pressed={f.persistent} onClick={() => setF({ ...f, persistent: !f.persistent })}>Persistent request</Button>
      <Box variant="small">Current Spot price ({f.type}): {(ph.data || []).slice(0, 3).map((p) => `${p.availabilityZone} $${p.spotPrice}`).join(" | ") || "-"}</Box>
    </FormModal>
  </SpaceBetween>);
}

// ── Reserved Instances ───────────────────────────────────────────────────────────────────────
export function ReservedInstances() {
  const notify = useNotify();
  const mine = useAsync(() => api.describeReservedInstances(), []);
  const [type, setType] = useState("m5.large");
  const [cls, setCls] = useState("standard");
  const offers = useAsync(() => api.describeRiOfferings({ InstanceType: type, OfferingClass: cls }), [type, cls]);
  const [sel, setSel] = useState([]);
  const [count, setCount] = useState("1");
  return page("Reserved Instances", "ec2.purchasing.reserved-instances", <SpaceBetween size="l">
    <ResourceTable resourceName="Reserved Instances" items={mine.data || []} loading={mine.loading} error={mine.error} onRefresh={mine.reload} trackBy="reservedInstancesId" filterPlaceholder="Filter Reserved Instances"
      empty={{ title: "No Reserved Instances", subtitle: "Purchase an offering below." }}
      columns={[
        { id: "id", header: "Reservation ID", isRowHeader: true, cell: (r) => r.reservedInstancesId }, { id: "t", header: "Instance type", cell: (r) => r.instanceType },
        { id: "c", header: "Count", cell: (r) => r.instanceCount }, { id: "cl", header: "Class", cell: (r) => r.offeringClass }, { id: "o", header: "Payment option", cell: (r) => r.offeringType },
        { id: "s", header: "State", cell: (r) => <StatusIndicator type={stateType(r.state)}>{r.state}</StatusIndicator> },
        { id: "st", header: "Start", cell: (r) => fmtDate(r.start) }, { id: "e", header: "End", cell: (r) => fmtDate(r.end) },
      ]} />
    <ResourceTable resourceName="Offerings" items={offers.data || []} loading={offers.loading} error={offers.error} onRefresh={offers.reload} trackBy="reservedInstancesOfferingId"
      selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter offerings" description="Prices are illustrative multiples of Vyomi's on-demand rate; nothing is billed."
      empty={{ title: "No offerings" }}
      columns={[
        { id: "id", header: "Offering ID", isRowHeader: true, cell: (r) => r.reservedInstancesOfferingId }, { id: "d", header: "Term", cell: (r) => `${Number(r.duration) / 31536000} year` },
        { id: "o", header: "Payment option", cell: (r) => r.offeringType }, { id: "f", header: "Upfront (USD)", cell: (r) => r.fixedPrice }, { id: "u", header: "Hourly (USD)", cell: (r) => r.usagePrice },
      ]}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Input value={type} onChange={({ detail }) => setType(detail.value)} ariaLabel="Offering instance type" />
        <Select selectedOption={opt(cls)} onChange={({ detail }) => setCls(detail.selectedOption.value)} ariaLabel="Offering class" options={["standard", "convertible"].map((v) => opt(v))} />
        <Input type="number" value={count} onChange={({ detail }) => setCount(detail.value)} ariaLabel="Purchase count" />
        <Button variant="primary" disabled={sel.length !== 1} onClick={async () => { try { const id = await api.purchaseRi(sel[0].reservedInstancesOfferingId, Number(count)); notify.success(`Purchased reservation ${id}.`); setSel([]); mine.reload(); } catch (e) { notify.error(e); } }}>Purchase</Button>
      </SpaceBetween>} />
  </SpaceBetween>);
}

// ── Capacity Reservations ────────────────────────────────────────────────────────────────────
export function CapacityReservations() {
  const notify = useNotify();
  const t = useAsync(() => api.describeCapacityReservations(), []);
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ type: "t3.micro", az: "us-east-1a", count: "1", platform: "Linux/UNIX", targeted: false });
  return page("Capacity Reservations", "ec2.purchasing.capacity-reservations", <>
    <ResourceTable resourceName="Capacity Reservations" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="capacityReservationId"
      selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter Capacity Reservations"
      empty={{ title: "No Capacity Reservations", subtitle: "Reserve capacity for an instance type in an Availability Zone." }}
      columns={[
        { id: "id", header: "Capacity Reservation ID", isRowHeader: true, cell: (r) => r.capacityReservationId }, { id: "t", header: "Instance type", cell: (r) => r.instanceType },
        { id: "az", header: "Availability Zone", cell: (r) => r.availabilityZone }, { id: "p", header: "Platform", cell: (r) => r.instancePlatform },
        { id: "tot", header: "Total capacity", cell: (r) => r.totalInstanceCount }, { id: "av", header: "Available capacity", cell: (r) => r.availableInstanceCount },
        { id: "m", header: "Match criteria", cell: (r) => r.instanceMatchCriteria }, { id: "s", header: "State", cell: (r) => <StatusIndicator type={stateType(r.state)}>{r.state}</StatusIndicator> },
      ]}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1 || sel[0]?.state !== "active"} onClick={async () => { try { await api.cancelCapacityReservation(sel[0].capacityReservationId); notify.success("Capacity Reservation cancelled."); setSel([]); t.reload(); } catch (e) { notify.error(e); } }}>Cancel reservation</Button>
        <Button variant="primary" onClick={() => setOpen(true)}>Create Capacity Reservation</Button>
      </SpaceBetween>} />
    <FormModal visible={open} title="Create Capacity Reservation" submit="Create" onDismiss={() => setOpen(false)}
      onSubmit={async () => { await api.createCapacityReservation({ InstanceType: f.type, AvailabilityZone: f.az, InstancePlatform: f.platform, InstanceCount: Number(f.count), InstanceMatchCriteria: f.targeted ? "targeted" : "open" }); notify.success("Capacity Reservation created."); t.reload(); }}>
      <FormField label="Instance type"><Input value={f.type} onChange={({ detail }) => setF({ ...f, type: detail.value })} ariaLabel="Instance type" /></FormField>
      <FormField label="Availability Zone"><Select selectedOption={opt(f.az)} onChange={({ detail }) => setF({ ...f, az: detail.selectedOption.value })} ariaLabel="Availability Zone" options={["us-east-1a", "us-east-1b", "us-east-1c"].map((v) => opt(v))} /></FormField>
      <FormField label="Platform"><Select selectedOption={opt(f.platform)} onChange={({ detail }) => setF({ ...f, platform: detail.selectedOption.value })} ariaLabel="Platform" options={["Linux/UNIX", "Red Hat Enterprise Linux", "SUSE Linux", "Windows"].map((v) => opt(v))} /></FormField>
      <FormField label="Number of instances"><Input type="number" value={f.count} onChange={({ detail }) => setF({ ...f, count: detail.value })} ariaLabel="Number of instances" /></FormField>
      <Button pressed={f.targeted} onClick={() => setF({ ...f, targeted: !f.targeted })}>Targeted only (instances must name this reservation)</Button>
    </FormModal>
  </>);
}

// ── Dedicated Hosts ──────────────────────────────────────────────────────────────────────────
export function DedicatedHosts() {
  const notify = useNotify();
  const t = useAsync(() => api.describeHosts(), []);
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ type: "m5.large", az: "us-east-1a", qty: "1", auto: false });
  return page("Dedicated Hosts", "ec2.purchasing.dedicated-hosts", <>
    <ResourceTable resourceName="Dedicated Hosts" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="hostId"
      selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter Dedicated Hosts"
      empty={{ title: "No Dedicated Hosts", subtitle: "Allocate a host to launch instances with host tenancy." }}
      columns={[
        { id: "id", header: "Host ID", isRowHeader: true, cell: (h) => h.hostId }, { id: "t", header: "Instance type", cell: (h) => h.hostProperties?.instanceType || `${h.hostProperties?.instanceFamily} family` },
        { id: "az", header: "Availability Zone", cell: (h) => h.availabilityZone }, { id: "s", header: "State", cell: (h) => <StatusIndicator type={stateType(h.state)}>{h.state}</StatusIndicator> },
        { id: "v", header: "Available vCPUs", cell: (h) => `${h.availableCapacity?.availableVCpus} / ${h.hostProperties?.totalVCpus}` },
        { id: "i", header: "Instances", cell: (h) => (h.instances ? (Array.isArray(h.instances.item) ? h.instances.item.length : 1) : 0) },
        { id: "ap", header: "Auto-placement", cell: (h) => h.autoPlacement },
      ]}
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Button disabled={sel.length !== 1 || sel[0]?.state !== "available"} onClick={async () => { try { const r = await api.releaseHosts([sel[0].hostId]); notify.success("Release requested."); setSel([]); t.reload(); return r; } catch (e) { notify.error(e); } }}>Release host</Button>
        <Button variant="primary" onClick={() => setOpen(true)}>Allocate Dedicated Host</Button>
      </SpaceBetween>} />
    <FormModal visible={open} title="Allocate Dedicated Host" submit="Allocate" onDismiss={() => setOpen(false)}
      onSubmit={async () => { await api.allocateHosts({ InstanceType: f.type, AvailabilityZone: f.az, Quantity: Number(f.qty), AutoPlacement: f.auto ? "on" : "off" }); notify.success("Dedicated Host allocated."); t.reload(); }}>
      <FormField label="Instance type"><Input value={f.type} onChange={({ detail }) => setF({ ...f, type: detail.value })} ariaLabel="Instance type" /></FormField>
      <FormField label="Availability Zone"><Select selectedOption={opt(f.az)} onChange={({ detail }) => setF({ ...f, az: detail.selectedOption.value })} ariaLabel="Availability Zone" options={["us-east-1a", "us-east-1b", "us-east-1c"].map((v) => opt(v))} /></FormField>
      <FormField label="Quantity"><Input type="number" value={f.qty} onChange={({ detail }) => setF({ ...f, qty: detail.value })} ariaLabel="Quantity" /></FormField>
      <Button pressed={f.auto} onClick={() => setF({ ...f, auto: !f.auto })}>Enable auto-placement</Button>
    </FormModal>
  </>);
}

// ── Settings tabs: Managed resources + Auto Scaling groups ───────────────────────────────────
export function ManagedResources() {
  const t = useAsync(() => Promise.all([api.describeInstances(), api.describeNetworkInterfaces(), api.describeSnapshots(), api.describeSpotRequests()]), []);
  const [insts, enis, snaps, spots] = t.data || [[], [], [], []];
  const rows = [
    ...insts.filter((i) => i.Tags?.["aws:autoscaling:groupName"]).map((i) => ({ id: i.instanceId, kind: "Instance", by: "Auto Scaling", ref: i.Tags["aws:autoscaling:groupName"] })),
    ...insts.filter((i) => i.instanceLifecycle === "spot").map((i) => ({ id: i.instanceId, kind: "Instance", by: "EC2 Spot", ref: i.spotInstanceRequestId })),
    ...enis.filter((e) => e.requesterManaged === "true" || e.interfaceType === "load_balancer").map((e) => ({ id: e.networkInterfaceId, kind: "Network interface", by: "Elastic Load Balancing", ref: e.description })),
    ...snaps.filter((s) => /^Created by (CreateImage|Data Lifecycle)/.test(s.description || "") || s.Tags?.["dlm:managed"]).map((s) => ({ id: s.snapshotId, kind: "Snapshot", by: /CreateImage/.test(s.description || "") ? "AMI creation" : "Data Lifecycle Manager", ref: s.description })),
  ];
  return (
    <CapabilityContainer id="ec2.settings.other" title="Managed resources" description="EC2 resources created and owned by other services, derived live from the resources' own tags and attributes.">
      {t.error ? <ErrorAlert error={t.error} /> : (
        <Table variant="embedded" loading={t.loading} items={rows} trackBy="id" data-testid="managed-resources"
          empty={<Box textAlign="center">No managed resources. Launch an Auto Scaling group, Spot instance or load balancer to see them here.</Box>}
          columnDefinitions={[{ id: "id", header: "Resource ID", cell: (r) => r.id }, { id: "k", header: "Type", cell: (r) => r.kind }, { id: "b", header: "Managed by", cell: (r) => r.by }, { id: "r", header: "Reference", cell: (r) => r.ref || "-" }]} />
      )}
    </CapabilityContainer>
  );
}

export function AsgAccountSettings() {
  const t = useAsync(() => Promise.all([api.asgAccountLimits(), api.describeAutoScalingGroups()]), []);
  const [lim, groups] = t.data || [{}, []];
  const kv = [["Auto Scaling groups", `${lim.NumberOfAutoScalingGroups ?? "-"} / ${lim.MaxNumberOfAutoScalingGroups ?? "-"}`], ["Launch configurations", `${lim.NumberOfLaunchConfigurations ?? "-"} / ${lim.MaxNumberOfLaunchConfigurations ?? "-"}`],
    ["Desired capacity (all groups)", groups.reduce((n, g) => n + Number(g.DesiredCapacity || 0), 0)], ["Instances in service", groups.reduce((n, g) => n + (g.Instances?.length || 0), 0)]];
  return (
    <CapabilityContainer id="ec2.settings.other" title="Auto Scaling group quotas and usage" description="Account quotas from DescribeAccountLimits and live usage from your groups.">
      {t.error ? <ErrorAlert error={t.error} /> : (
        <ColumnLayout columns={4} variant="text-grid" data-testid="asg-settings">
          {kv.map(([k, v]) => <div key={k}><Box variant="awsui-key-label">{k}</Box><div>{v}</div></div>)}
        </ColumnLayout>
      )}
    </CapabilityContainer>
  );
}
