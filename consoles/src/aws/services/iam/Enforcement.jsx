/* IAM enforcement (Off / Audit / Enforce) + decision audit list. Cloudscape-native.
 *   <EnforcementPanel service resource />  compact per-resource control (S3 bucket Permissions, IAM role/user detail)
 *   default export                          the IAM > Enforcement page: global, space, per-service, per-resource overrides + Audit tab */
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
import SegmentedControl from "@cloudscape-design/components/segmented-control";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import { ServicePicker, ResourceArnPicker } from "../../kit/PermissionPicker.jsx";
import { MODES, MODE_LABEL, MODE_HELP, SOURCE_LABEL, SERVICES, auditLabel, filterAudit } from "../../../common/iamEnforce.js";
import { useAudit, useEnforcement } from "../../../common/iamEnforceHooks.js";

const CLOUD = "aws";
const modeOptions = (inherit) => [...(inherit ? [{ id: "inherit", text: "Inherit" }] : []), ...MODES.map((m) => ({ id: m, text: MODE_LABEL[m] }))];
const modeType = { off: "stopped", audit: "warning", enforce: "success" };

export const ModeBadge = ({ mode }) => <StatusIndicator type={modeType[mode] || "stopped"}>{MODE_LABEL[mode] || mode}</StatusIndicator>;

function ModeControl({ value, onChange, disabled, inherit, ariaLabel }) {
  return <SegmentedControl selectedId={value} onChange={({ detail }) => onChange(detail.selectedId)} options={modeOptions(inherit)} label={ariaLabel} />;
}

/* Compact panel for a resource page. `resource` = the ARN; `service` = IAM prefix (s3, iam, ...). */
export function EnforcementPanel({ service, resource, title = "IAM enforcement" }) {
  const e = useEnforcement(CLOUD);
  if (e.loading) return <Container header={<Header variant="h2">{title}</Header>}><StatusIndicator type="loading">Loading</StatusIndicator></Container>;
  if (e.error && !e.settings) return <Container header={<Header variant="h2">{title}</Header>}><Alert type="error" header="Could not load enforcement settings">{e.error.message}</Alert></Container>;
  const eff = e.resolve(service, resource);
  const own = e.settings.resources[resource];
  return (
    <Container header={<Header variant="h2" description="Evaluate this resource's IAM policies on every request to it. Off by default.">{title}</Header>} data-testid="iam-enforce-panel">
      <SpaceBetween size="m">
        <div><Box variant="awsui-key-label">Effective mode</Box>
          <SpaceBetween direction="horizontal" size="xs"><ModeBadge mode={eff.mode} /><Box color="text-body-secondary">set by {SOURCE_LABEL[eff.source]}</Box></SpaceBetween>
          <Box variant="small" color="text-body-secondary">{MODE_HELP[eff.mode]}</Box></div>
        <FormField label="Resource override" description="Inherit follows the service, space and global settings.">
          <ModeControl ariaLabel="Resource enforcement mode" value={own || "inherit"} inherit disabled={e.saving} onChange={(m) => e.set("resource", resource, m)} />
        </FormField>
        {e.error && <Alert type="error">{e.error.message}</Alert>}
      </SpaceBetween>
    </Container>
  );
}

function SettingsTab() {
  const e = useEnforcement(CLOUD);
  const [svc, setSvc] = useState(null);
  const [res, setRes] = useState("");
  if (e.loading) return <StatusIndicator type="loading">Loading</StatusIndicator>;
  if (e.error && !e.settings) return <Alert type="error" header="Could not load enforcement settings">{e.error.message}</Alert>;
  const s = e.settings;
  const svcRows = [...new Set([...SERVICES[CLOUD], ...Object.keys(s.services)])].map((k) => ({ key: k, mode: s.services[k] }));
  const resRows = Object.entries(s.resources).map(([k, mode]) => ({ key: k, mode }));
  return (
    <SpaceBetween size="l">
      {e.error && <Alert type="error">{e.error.message}</Alert>}
      <Container header={<Header variant="h2" description="Most specific wins: resource, then service, then space, then global.">Default modes</Header>}>
        <SpaceBetween size="m">
          <FormField label="Global"><ModeControl ariaLabel="Global enforcement mode" value={s.global} disabled={e.saving} onChange={(m) => e.set("global", null, m)} /></FormField>
          <FormField label="This space"><ModeControl ariaLabel="Space enforcement mode" value={s.space} disabled={e.saving} onChange={(m) => e.set("space", null, m)} /></FormField>
        </SpaceBetween>
      </Container>
      <Table variant="container" header={<Header variant="h2" counter={`(${svcRows.length})`} actions={<ServicePicker value={null} ariaLabel="Add service override" placeholder="Add a service" onChange={(v) => e.set("service", v, "audit")} />}>Per-service</Header>} items={svcRows} trackBy="key"
        columnDefinitions={[
          { id: "svc", header: "Service", cell: (r) => r.key },
          { id: "eff", header: "Effective mode", cell: (r) => { const x = e.resolve(r.key); return <SpaceBetween direction="horizontal" size="xs"><ModeBadge mode={x.mode} /><Box color="text-body-secondary">{SOURCE_LABEL[x.source]}</Box></SpaceBetween>; } },
          { id: "set", header: "Override", cell: (r) => <ModeControl ariaLabel={`${r.key} enforcement mode`} value={r.mode || "inherit"} inherit disabled={e.saving} onChange={(m) => e.set("service", r.key, m)} /> },
        ]} />
      <Table variant="container" header={<Header variant="h2" counter={`(${resRows.length})`}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <ServicePicker value={svc} onChange={(v) => { setSvc(v); setRes(""); }} ariaLabel="Service" />
          <ResourceArnPicker service={svc} value={res} onChange={setRes} />
          <Button disabled={!res} onClick={() => { e.set("resource", res, "audit"); setRes(""); }}>Add override</Button>
        </SpaceBetween>}>Per-resource overrides</Header>} items={resRows} trackBy="key"
        columnDefinitions={[
          { id: "r", header: "Resource", cell: (r) => <Box variant="code">{r.key}</Box> },
          { id: "set", header: "Mode", cell: (r) => <ModeControl ariaLabel={`${r.key} enforcement mode`} value={r.mode} inherit disabled={e.saving} onChange={(m) => e.set("resource", r.key, m)} /> },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No resource overrides</b><Box variant="p" color="inherit">Resources follow their service, space or global mode.</Box></Box>} />
    </SpaceBetween>
  );
}

export function AuditList({ limit = 100 }) {
  const a = useAudit(CLOUD, limit);
  const [mode, setMode] = useState("all");
  const [dec, setDec] = useState("all");
  const rows = filterAudit(a.data || [], { mode, decision: dec });
  const sel = (v, opts) => ({ selectedOption: opts.find((o) => o.value === v), options: opts });
  const MO = [{ value: "all", label: "All modes" }, ...MODES.map((m) => ({ value: m, label: MODE_LABEL[m] }))];
  const DO = [{ value: "all", label: "All decisions" }, { value: "allow", label: "Allowed" }, { value: "deny", label: "Denied or would deny" }, { value: "would_deny", label: "Would deny (audit)" }];
  return (
    <Table variant="container" loading={a.loading} items={rows} trackBy="ts"
      header={<Header variant="h2" counter={`(${rows.length})`} description={`Last ${limit} IAM decisions. Read-only.`} actions={<Button iconName="refresh" onClick={a.reload} ariaLabel="Refresh" />}>Audit</Header>}
      filter={<SpaceBetween direction="horizontal" size="xs">
        <Select {...sel(mode, MO)} onChange={({ detail }) => setMode(detail.selectedOption.value)} ariaLabel="Filter by mode" />
        <Select {...sel(dec, DO)} onChange={({ detail }) => setDec(detail.selectedOption.value)} ariaLabel="Filter by decision" />
      </SpaceBetween>}
      columnDefinitions={[
        { id: "ts", header: "Time", cell: (r) => r.ts },
        { id: "p", header: "Principal", cell: (r) => r.principal },
        { id: "a", header: "Action", cell: (r) => r.action },
        { id: "r", header: "Resource", cell: (r) => r.resource },
        { id: "m", header: "Mode", cell: (r) => MODE_LABEL[r.mode] || r.mode },
        { id: "d", header: "Decision", cell: (r) => r.wouldDeny ? <Badge color="red">Would deny</Badge> : <StatusIndicator type={r.allowed ? "success" : "error"}>{auditLabel(r)}</StatusIndicator> },
        { id: "why", header: "Reason", cell: (r) => r.reason },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No decisions recorded</b><Box variant="p" color="inherit">Decisions appear here once a mode other than Off is set.</Box></Box>} />
  );
}

export default function EnforcementPage() {
  return (
    <ContentLayout header={<Header variant="h1" description="Choose how IAM policies are applied to requests in this space: Off, Audit (log would-deny) or Enforce.">Enforcement</Header>}>
      <Tabs tabs={[
        { id: "settings", label: "Settings", content: <SettingsTab /> },
        { id: "audit", label: "Audit", content: <AuditList /> },
      ]} />
    </ContentLayout>
  );
}
