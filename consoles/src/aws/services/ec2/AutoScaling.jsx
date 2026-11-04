/* EC2 console → Auto Scaling → Auto Scaling groups. Native wire: core/autoscaling_core.py's
 * Query-protocol engine (separate "autoscaling" AWS service, same /_wire) — real EC2
 * instances via vpc_core's RunInstances/TerminateInstances lifecycle. See ec2.auto-scaling. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Multiselect from "@cloudscape-design/components/multiselect";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Table from "@cloudscape-design/components/table";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import * as api from "./api.js";

const opt = (v, label) => ({ value: v, label: label || v });

export function AutoScalingGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeAutoScalingGroups(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Auto Scaling groups</Header>}>
      <ResourceTable
        resourceName="Auto Scaling Groups"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="AutoScalingGroupName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find Auto Scaling groups"
        empty={{ title: "No Auto Scaling groups", subtitle: "You don't have any Auto Scaling groups yet." }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => <Link href={href("ec2", "auto-scaling-groups", g.AutoScalingGroupName)} onFollow={follow}>{g.AutoScalingGroupName}</Link> },
          { id: "desired", header: "Desired", cell: (g) => g.DesiredCapacity },
          { id: "min", header: "Min", cell: (g) => g.MinSize },
          { id: "max", header: "Max", cell: (g) => g.MaxSize },
          { id: "instances", header: "Instances", cell: (g) => g.Instances.length },
          { id: "az", header: "Availability Zones", cell: (g) => (g.AvailabilityZones || []).join(", ") },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "view", text: "View details", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "view") navigate("ec2", "auto-scaling-groups", sel[0].AutoScalingGroupName);
              else setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-auto-scaling-group")} onFollow={follow}>Create Auto Scaling group</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="Auto Scaling group" names={sel.map((g) => g.AutoScalingGroupName)} onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteAutoScalingGroup(g.AutoScalingGroupName, true); notify.success(`${sel.length} Auto Scaling group(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function CreateAutoScalingGroup() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [ltId, setLtId] = useState("");
  const [min, setMin] = useState("1");
  const [max, setMax] = useState("3");
  const [desired, setDesired] = useState("1");
  const [subnetIds, setSubnetIds] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const templates = useAsync(() => api.describeLaunchTemplates(), []).data || [];
  const subnets = useAsync(() => api.describeSubnets(), []).data || [];

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createAutoScalingGroup({
        AutoScalingGroupName: name, MinSize: min, MaxSize: max, DesiredCapacity: desired,
        LaunchTemplate: ltId ? { LaunchTemplateId: ltId, Version: "$Default" } : undefined,
        VPCZoneIdentifier: subnetIds.length ? subnetIds.map((o) => o.value).join(",") : undefined,
      });
      notify.success(`Auto Scaling group "${name}" created.`);
      navigate("ec2", "auto-scaling-groups", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create Auto Scaling group</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "auto-scaling-groups")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name || !ltId} onClick={submit}>Create Auto Scaling group</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Group details</Header>}>
            <SpaceBetween size="l">
              <FormField label="Auto Scaling group name"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-asg" ariaLabel="Auto Scaling group name" /></FormField>
              <FormField label="Launch template"><Select selectedOption={ltId ? opt(ltId, templates.find((t) => t.launchTemplateId === ltId)?.launchTemplateName) : null}
                onChange={({ detail }) => setLtId(detail.selectedOption.value)}
                options={templates.map((t) => opt(t.launchTemplateId, t.launchTemplateName))} placeholder="Select a launch template" ariaLabel="Launch template" /></FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Network</Header>}>
            <FormField label="Subnets"><Multiselect selectedOptions={subnetIds} onChange={({ detail }) => setSubnetIds(detail.selectedOptions)}
              options={subnets.map((s) => opt(s.subnetId, `${s.subnetId} (${s.availabilityZone})`))} placeholder="Select subnets" ariaLabel="Subnets" /></FormField>
          </Container>
          <Container header={<Header variant="h2">Group size</Header>}>
            <SpaceBetween size="l" direction="horizontal">
              <FormField label="Desired capacity"><Input type="number" value={desired} onChange={({ detail }) => setDesired(detail.value)} ariaLabel="Desired capacity" /></FormField>
              <FormField label="Minimum capacity"><Input type="number" value={min} onChange={({ detail }) => setMin(detail.value)} ariaLabel="Minimum capacity" /></FormField>
              <FormField label="Maximum capacity"><Input type="number" value={max} onChange={({ detail }) => setMax(detail.value)} ariaLabel="Maximum capacity" /></FormField>
            </SpaceBetween>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}

export function AutoScalingGroupDetail({ params }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeAutoScalingGroup(params.id), [params.id]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Auto Scaling group not found" }} />;
  const g = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
    }>{g.AutoScalingGroupName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["Desired capacity", g.DesiredCapacity], ["Minimum capacity", g.MinSize], ["Maximum capacity", g.MaxSize],
          ["Launch template", g.LaunchTemplate ? `${g.LaunchTemplate.LaunchTemplateName || g.LaunchTemplate.LaunchTemplateId} (${g.LaunchTemplate.Version})` : "-"],
          ["Health check type", g.HealthCheckType], ["Health check grace period", `${g.HealthCheckGracePeriod}s`],
          ["Default instance warmup", `${g.DefaultInstanceWarmup}s`], ["Created", g.CreatedTime],
        ]} />
        <Tabs tabs={[
          { id: "activity", label: "Activity", content: <InstancesTab g={g} reload={t.reload} /> },
          { id: "scaling", label: "Automatic scaling", content: <ScalingPoliciesTab g={g} /> },
          { id: "scheduled", label: "Scheduled actions", content: <ScheduledActionsTab g={g} /> },
          { id: "lifecycle", label: "Instance management", content: <LifecycleHooksTab g={g} reload={t.reload} /> },
          { id: "refresh", label: "Instance refresh", content: <InstanceRefreshTab g={g} reload={t.reload} /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={del} resourceType="Auto Scaling group" names={[g.AutoScalingGroupName]} onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteAutoScalingGroup(g.AutoScalingGroupName, true); notify.success("Auto Scaling group deleted."); navigate("ec2", "auto-scaling-groups"); }} />
    </ContentLayout>
  );
}

function InstancesTab({ g, reload }) {
  const notify = useNotify();
  const [desired, setDesired] = useState(String(g.DesiredCapacity));
  return (
    <SpaceBetween size="l">
      <Table
        items={g.Instances}
        trackBy="InstanceId"
        header={<Header variant="h2" counter={`(${g.Instances.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Input type="number" value={desired} onChange={({ detail }) => setDesired(detail.value)} ariaLabel="Desired capacity" />
            <Button onClick={async () => { await api.setDesiredCapacity(g.AutoScalingGroupName, desired); notify.success("Desired capacity updated."); reload(); }}>Set desired capacity</Button>
          </SpaceBetween>
        }>Instances</Header>}
        columnDefinitions={[
          { id: "id", header: "Instance", isRowHeader: true, cell: (i) => <Link href={href("ec2", "instances", i.InstanceId)} onFollow={follow}>{i.InstanceId}</Link> },
          { id: "lifecycle", header: "Lifecycle", cell: (i) => <StatusIndicator type={i.LifecycleState === "InService" ? "success" : "pending"}>{i.LifecycleState}</StatusIndicator> },
          { id: "health", header: "Health status", cell: (i) => i.HealthStatus },
          { id: "protected", header: "Protected from scale in", cell: (i) => i.ProtectedFromScaleIn },
        ]}
        empty={<Box textAlign="center" color="inherit">No instances.</Box>}
      />
    </SpaceBetween>
  );
}

const POLICY_TYPES = [opt("SimpleScaling", "Simple scaling"), opt("StepScaling", "Step scaling"), opt("TargetTrackingScaling", "Target tracking scaling")];

function ScalingPoliciesTab({ g }) {
  const notify = useNotify();
  const [creating, setCreating] = useState(false);
  const [sel, setSel] = useState([]);
  const t = useAsync(() => api.describeScalingPolicies(g.AutoScalingGroupName), [g.AutoScalingGroupName]);
  const rows = t.data || [];
  return (
    <SpaceBetween size="l">
      <Table
        items={rows}
        trackBy="PolicyName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const p of sel) await api.deleteScalingPolicy(g.AutoScalingGroupName, p.PolicyName); notify.success("Policy(ies) deleted."); setSel([]); t.reload(); }}>Delete</Button>
            <Button variant="primary" onClick={() => setCreating(true)}>Create scaling policy</Button>
          </SpaceBetween>
        }>Scaling policies</Header>}
        columnDefinitions={[
          { id: "name", header: "Policy name", isRowHeader: true, cell: (p) => p.PolicyName },
          { id: "type", header: "Policy type", cell: (p) => p.PolicyType },
          { id: "adj", header: "Adjustment", cell: (p) => (p.PolicyType === "TargetTrackingScaling" ? `target ${p.TargetTrackingConfiguration?.TargetValue}` : p.PolicyType === "StepScaling" ? `${p.StepAdjustments.length} step(s)` : `${p.AdjustmentType} ${p.ScalingAdjustment}`) },
          { id: "arn", header: "ARN", cell: (p) => p.PolicyARN },
        ]}
        empty={<Box textAlign="center" color="inherit">No scaling policies. Attach a policy's ARN to a CloudWatch alarm action to scale automatically.</Box>}
      />
      <CreatePolicyModal visible={creating} g={g} onDismiss={() => setCreating(false)} onDone={() => { setCreating(false); t.reload(); }} />
    </SpaceBetween>
  );
}

function CreatePolicyModal({ visible, g, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [type, setType] = useState("SimpleScaling");
  const [adjType, setAdjType] = useState("ChangeInCapacity");
  const [adj, setAdj] = useState("1");
  const [target, setTarget] = useState("50");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const input = { PolicyName: name, PolicyType: type };
      if (type === "SimpleScaling") Object.assign(input, { AdjustmentType: adjType, ScalingAdjustment: adj });
      else if (type === "StepScaling") Object.assign(input, { AdjustmentType: adjType, StepAdjustments: [{ MetricIntervalLowerBound: 0, ScalingAdjustment: adj }] });
      else Object.assign(input, { TargetTrackingConfiguration: { TargetValue: target } });
      await api.putScalingPolicy(g.AutoScalingGroupName, input);
      notify.success(`Scaling policy "${name}" created.`);
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create scaling policy" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Policy name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Policy name" /></FormField>
        <FormField label="Policy type"><Select selectedOption={POLICY_TYPES.find((o) => o.value === type)} onChange={({ detail }) => setType(detail.selectedOption.value)} options={POLICY_TYPES} ariaLabel="Policy type" /></FormField>
        {type !== "TargetTrackingScaling" && (
          <>
            <FormField label="Adjustment type"><Select selectedOption={opt(adjType)} onChange={({ detail }) => setAdjType(detail.selectedOption.value)} options={["ChangeInCapacity", "ExactCapacity", "PercentChangeInCapacity"].map((v) => opt(v))} ariaLabel="Adjustment type" /></FormField>
            <FormField label={type === "StepScaling" ? "First step adjustment" : "Scaling adjustment"}><Input type="number" value={adj} onChange={({ detail }) => setAdj(detail.value)} ariaLabel="Scaling adjustment" /></FormField>
          </>
        )}
        {type === "TargetTrackingScaling" && <FormField label="Target value"><Input type="number" value={target} onChange={({ detail }) => setTarget(detail.value)} ariaLabel="Target value" /></FormField>}
      </SpaceBetween>
    </Modal>
  );
}

function ScheduledActionsTab({ g }) {
  const notify = useNotify();
  const [creating, setCreating] = useState(false);
  const [sel, setSel] = useState([]);
  const t = useAsync(() => api.describeScheduledActions(g.AutoScalingGroupName), [g.AutoScalingGroupName]);
  const rows = t.data || [];
  return (
    <SpaceBetween size="l">
      <Table
        items={rows}
        trackBy="ScheduledActionName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const a of sel) await api.deleteScheduledAction(g.AutoScalingGroupName, a.ScheduledActionName); notify.success("Scheduled action(s) deleted."); setSel([]); t.reload(); }}>Delete</Button>
            <Button variant="primary" onClick={() => setCreating(true)}>Create scheduled action</Button>
          </SpaceBetween>
        }>Scheduled actions</Header>}
        columnDefinitions={[
          { id: "name", header: "Name", isRowHeader: true, cell: (a) => a.ScheduledActionName },
          { id: "recur", header: "Recurrence", cell: (a) => a.Recurrence || "-" },
          { id: "start", header: "Start time", cell: (a) => a.StartTime || "-" },
          { id: "cap", header: "Min / Max / Desired", cell: (a) => `${a.MinSize ?? "-"} / ${a.MaxSize ?? "-"} / ${a.DesiredCapacity ?? "-"}` },
        ]}
        empty={<Box textAlign="center" color="inherit">No scheduled actions.</Box>}
      />
      <CreateScheduledActionModal visible={creating} g={g} onDismiss={() => setCreating(false)} onDone={() => { setCreating(false); t.reload(); }} />
    </SpaceBetween>
  );
}

function CreateScheduledActionModal({ visible, g, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [mode, setMode] = useState("recurrence");
  const [recurrence, setRecurrence] = useState("0 9 * * *");
  const [startTime, setStartTime] = useState("");
  const [desired, setDesired] = useState(String(g.DesiredCapacity));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.putScheduledAction(g.AutoScalingGroupName, {
        ScheduledActionName: name, DesiredCapacity: desired,
        Recurrence: mode === "recurrence" ? recurrence : undefined,
        StartTime: mode === "once" ? new Date(startTime).toISOString().replace(/\.\d{3}Z$/, "Z") : undefined,
      });
      notify.success(`Scheduled action "${name}" created.`);
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create scheduled action" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
        <FormField label="Schedule"><RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)} items={[{ value: "recurrence", label: "Recurring schedule (cron)" }, { value: "once", label: "One-time, at a specific date and time" }]} /></FormField>
        {mode === "recurrence"
          ? <FormField label="Recurrence" constraintText="5-field cron: minute hour day-of-month month day-of-week."><Input value={recurrence} onChange={({ detail }) => setRecurrence(detail.value)} ariaLabel="Recurrence" /></FormField>
          : <FormField label="Start time"><Input type="datetime-local" value={startTime} onChange={({ detail }) => setStartTime(detail.value)} ariaLabel="Start time" /></FormField>}
        <FormField label="Desired capacity"><Input type="number" value={desired} onChange={({ detail }) => setDesired(detail.value)} ariaLabel="Desired capacity" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

const TRANSITIONS = [opt("autoscaling:EC2_INSTANCE_LAUNCHING", "Instance launch"), opt("autoscaling:EC2_INSTANCE_TERMINATING", "Instance terminate")];

function LifecycleHooksTab({ g, reload }) {
  const notify = useNotify();
  const [creating, setCreating] = useState(false);
  const [sel, setSel] = useState([]);
  const t = useAsync(() => api.describeLifecycleHooks(g.AutoScalingGroupName), [g.AutoScalingGroupName]);
  const rows = t.data || [];
  const pending = g.Instances.filter((i) => i.LifecycleState === "Pending:Wait" || i.LifecycleState === "Terminating:Wait");
  return (
    <SpaceBetween size="l">
      <Table
        items={rows}
        trackBy="LifecycleHookName"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const h of sel) await api.deleteLifecycleHook(g.AutoScalingGroupName, h.LifecycleHookName); notify.success("Lifecycle hook(s) deleted."); setSel([]); t.reload(); }}>Delete</Button>
            <Button variant="primary" onClick={() => setCreating(true)}>Create lifecycle hook</Button>
          </SpaceBetween>
        }>Lifecycle hooks</Header>}
        columnDefinitions={[
          { id: "name", header: "Name", isRowHeader: true, cell: (h) => h.LifecycleHookName },
          { id: "transition", header: "Lifecycle transition", cell: (h) => h.LifecycleTransition },
          { id: "default", header: "Default result", cell: (h) => h.DefaultResult },
        ]}
        empty={<Box textAlign="center" color="inherit">No lifecycle hooks. Instances transition immediately.</Box>}
      />
      {pending.length > 0 && (
        <Table
          items={pending}
          trackBy="InstanceId"
          header={<Header variant="h2" counter={`(${pending.length})`}>Instances waiting on a lifecycle action</Header>}
          columnDefinitions={[
            { id: "id", header: "Instance", cell: (i) => <Link href={href("ec2", "instances", i.InstanceId)} onFollow={follow}>{i.InstanceId}</Link> },
            { id: "state", header: "Lifecycle state", cell: (i) => <StatusIndicator type="pending">{i.LifecycleState}</StatusIndicator> },
            { id: "action", header: "", cell: (i) => (
              <Button onClick={async () => {
                const hook = rows.find((h) => h.LifecycleTransition === (i.LifecycleState === "Pending:Wait" ? "autoscaling:EC2_INSTANCE_LAUNCHING" : "autoscaling:EC2_INSTANCE_TERMINATING"));
                if (!hook) return;
                await api.completeLifecycleAction(g.AutoScalingGroupName, hook.LifecycleHookName, i.InstanceId, "CONTINUE");
                notify.success(`Lifecycle action completed for ${i.InstanceId}.`); t.reload(); reload();
              }}>Complete lifecycle action</Button>
            ) },
          ]}
        />
      )}
      <CreateLifecycleHookModal visible={creating} g={g} onDismiss={() => setCreating(false)} onDone={() => { setCreating(false); t.reload(); }} />
    </SpaceBetween>
  );
}

function CreateLifecycleHookModal({ visible, g, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [transition, setTransition] = useState(TRANSITIONS[0].value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.putLifecycleHook(g.AutoScalingGroupName, { LifecycleHookName: name, LifecycleTransition: transition });
      notify.success(`Lifecycle hook "${name}" created.`);
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create lifecycle hook" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
        <FormField label="Lifecycle transition"><Select selectedOption={TRANSITIONS.find((o) => o.value === transition)} onChange={({ detail }) => setTransition(detail.selectedOption.value)} options={TRANSITIONS} ariaLabel="Lifecycle transition" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

function InstanceRefreshTab({ g, reload }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeInstanceRefreshes(g.AutoScalingGroupName), [g.AutoScalingGroupName]);
  const rows = t.data || [];
  const inProgress = rows.some((r) => r.Status === "InProgress");
  return (
    <Table
      items={rows}
      trackBy="InstanceRefreshId"
      header={<Header variant="h2" counter={`(${rows.length})`} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!inProgress} onClick={async () => { await api.cancelInstanceRefresh(g.AutoScalingGroupName); notify.success("Instance refresh cancelled."); t.reload(); }}>Cancel refresh</Button>
          <Button variant="primary" disabled={inProgress} onClick={async () => { await api.startInstanceRefresh(g.AutoScalingGroupName); notify.success("Instance refresh started."); t.reload(); reload(); }}>Start instance refresh</Button>
        </SpaceBetween>
      }>Instance refresh history</Header>}
      columnDefinitions={[
        { id: "id", header: "Instance refresh ID", isRowHeader: true, cell: (r) => r.InstanceRefreshId },
        { id: "status", header: "Status", cell: (r) => <StatusIndicator type={r.Status === "Successful" ? "success" : r.Status === "Cancelled" ? "stopped" : "pending"}>{r.Status}</StatusIndicator> },
        { id: "pct", header: "Percentage complete", cell: (r) => `${r.PercentageComplete}%` },
        { id: "instances", header: "Instances to update", cell: (r) => r.InstancesToUpdate },
        { id: "start", header: "Start time", cell: (r) => r.StartTime },
      ]}
      empty={<Box textAlign="center" color="inherit">No instance refreshes yet.</Box>}
    />
  );
}
