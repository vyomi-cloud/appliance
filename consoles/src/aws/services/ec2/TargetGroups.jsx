/* EC2 console → Load Balancing → Target groups. Native wire: core/elbv2_core.py's
 * Query-protocol engine (separate "elasticloadbalancing" AWS service, same /_wire). Target
 * health is deterministic (healthy once attached to a listener, else unused) — the engine
 * is control-plane only, there's no real L7 data plane behind it. */
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
import TagEditor from "@cloudscape-design/components/tag-editor";
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
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import { opt, ALB_PROTOCOLS, NLB_PROTOCOLS, ElbTagsTab } from "./elbv2-shared.jsx";
import * as api from "./api.js";

const TG_PROTOCOLS = [...ALB_PROTOCOLS, ...NLB_PROTOCOLS];
const TARGET_TYPES = [{ value: "instance", label: "Instances" }, { value: "ip", label: "IP addresses" }, { value: "lambda", label: "Lambda function" }];

export function TargetGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeTargetGroups(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Target groups</Header>}>
      <ResourceTable
        resourceName="Target Groups"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="TargetGroupArn"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find target groups by attribute or tag"
        empty={{ title: "No target groups", subtitle: "You don't have any target groups configured." }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => <Link href={href("ec2", "target-groups", g.TargetGroupName)} onFollow={follow}>{g.TargetGroupName}</Link> },
          { id: "proto", header: "Protocol : Port", cell: (g) => (g.Protocol ? `${g.Protocol}:${g.Port}` : "-") },
          { id: "ttype", header: "Target type", cell: (g) => g.TargetType },
          { id: "lb", header: "Load balancer", cell: (g) => (g.LoadBalancerArns.length ? g.LoadBalancerArns.map((a) => a.split("/")[2]).join(", ") : "-") },
          { id: "vpc", header: "VPC ID", cell: (g) => g.VpcId || "N/A" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "view", text: "View details", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "view") navigate("ec2", "target-groups", sel[0].TargetGroupName);
              else setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-target-group")} onFollow={follow}>Create target group</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="target group" names={sel.map((g) => g.TargetGroupName)} onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteTargetGroup(g.TargetGroupArn); notify.success(`${sel.length} target group(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function TargetGroupDetail({ params }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeTargetGroups({ Names: [params.id] }).then((xs) => xs[0]), [params.id]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Target group not found" }} />;
  const g = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
    }>{g.TargetGroupName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["Protocol", g.Protocol || "-"], ["Port", g.Port ?? "-"], ["Target type", g.TargetType], ["VPC ID", g.VpcId || "N/A"],
          ["IP address type", g.IpAddressType], ["Protocol version", g.ProtocolVersion || "-"],
          ["Load balancer", g.LoadBalancerArns.length ? g.LoadBalancerArns.map((a) => a.split("/")[2]).join(", ") : "-"],
        ]} />
        <Tabs tabs={[
          { id: "targets", label: "Targets", content: <TargetsTab g={g} reload={t.reload} /> },
          { id: "health", label: "Health checks", content: <HealthChecksTab g={g} reload={t.reload} /> },
          { id: "monitoring", label: "Monitoring", content: <CapabilityContainer id="ec2.load-balancing.monitoring" title="CloudWatch metrics" /> },
          { id: "attributes", label: "Attributes", content: <AttributesTab g={g} /> },
          { id: "tags", label: "Tags", content: <ElbTagsTab arn={g.TargetGroupArn} /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={del} resourceType="target group" names={[g.TargetGroupName]} onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteTargetGroup(g.TargetGroupArn); notify.success("Target group deleted."); navigate("ec2", "target-groups"); }} />
    </ContentLayout>
  );
}

function HealthState({ th }) {
  const state = th?.State;
  return <StatusIndicator type={state === "healthy" ? "success" : state === "unhealthy" ? "error" : "pending"}>{state || "unknown"}</StatusIndicator>;
}

function TargetsTab({ g, reload }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [registering, setRegistering] = useState(false);
  const t = useAsync(() => api.describeTargetHealth(g.TargetGroupArn), [g.TargetGroupArn]);
  const rows = t.data || [];

  return (
    <SpaceBetween size="l">
      <Table
        items={rows}
        loading={t.loading}
        trackBy={(r) => `${r.Target.Id}:${r.Target.Port}`}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { await api.deregisterTargets(g.TargetGroupArn, sel.map((r) => ({ Id: r.Target.Id, Port: r.Target.Port }))); notify.success("Target(s) deregistered."); setSel([]); t.reload(); reload(); }}>Deregister</Button>
            <Button variant="primary" onClick={() => setRegistering(true)}>Register targets</Button>
          </SpaceBetween>
        }>Registered targets</Header>}
        columnDefinitions={[
          { id: "id", header: "Target", isRowHeader: true, cell: (r) => r.Target.Id },
          { id: "port", header: "Port", cell: (r) => r.Target.Port },
          { id: "zone", header: "Availability Zone", cell: (r) => r.Target.AvailabilityZone || "-" },
          { id: "health", header: "Health status", cell: (r) => <HealthState th={r.TargetHealth} /> },
          { id: "reason", header: "Health status details", cell: (r) => r.TargetHealth?.Description || "-" },
        ]}
        empty={<Box textAlign="center" color="inherit">No registered targets.</Box>}
      />
      <RegisterTargetsModal visible={registering} g={g} onDismiss={() => setRegistering(false)} onDone={() => { setRegistering(false); t.reload(); reload(); }} />
    </SpaceBetween>
  );
}

function RegisterTargetsModal({ visible, g, onDismiss, onDone }) {
  const notify = useNotify();
  const [picked, setPicked] = useState([]);
  const [ips, setIps] = useState("");
  const [lambdaArn, setLambdaArn] = useState("");
  const [port, setPort] = useState(String(g.Port || 80));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const instances = useAsync(() => (g.TargetType === "instance" ? api.describeInstances() : Promise.resolve([])), [visible]).data || [];

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      let targets = [];
      if (g.TargetType === "instance") targets = picked.map((o) => ({ Id: o.value, Port: port }));
      else if (g.TargetType === "ip") targets = ips.split(",").map((s) => s.trim()).filter(Boolean).map((ip) => ({ Id: ip, Port: port }));
      else targets = lambdaArn ? [{ Id: lambdaArn }] : [];
      if (!targets.length) throw new Error("Add at least one target.");
      await api.registerTargets(g.TargetGroupArn, targets);
      notify.success(`${targets.length} target(s) registered.`);
      onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Register targets" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Register</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        {g.TargetType === "instance" && (
          <>
            <FormField label="Instances"><Multiselect selectedOptions={picked} onChange={({ detail }) => setPicked(detail.selectedOptions)}
              options={instances.map((i) => opt(i.instanceId, `${i.instanceId} (${i.instanceState?.name})`))} placeholder="Select instances" ariaLabel="Instances" /></FormField>
            <FormField label="Port"><Input type="number" value={port} onChange={({ detail }) => setPort(detail.value)} ariaLabel="Port" /></FormField>
          </>
        )}
        {g.TargetType === "ip" && (
          <>
            <FormField label="IP addresses (comma-separated)"><Input value={ips} onChange={({ detail }) => setIps(detail.value)} placeholder="10.0.1.10, 10.0.1.11" ariaLabel="IP addresses" /></FormField>
            <FormField label="Port"><Input type="number" value={port} onChange={({ detail }) => setPort(detail.value)} ariaLabel="Port" /></FormField>
          </>
        )}
        {g.TargetType === "lambda" && (
          <FormField label="Lambda function ARN"><Input value={lambdaArn} onChange={({ detail }) => setLambdaArn(detail.value)} placeholder="arn:aws:lambda:us-east-1:123456789012:function:..." ariaLabel="Lambda function ARN" /></FormField>
        )}
      </SpaceBetween>
    </Modal>
  );
}

function HealthChecksTab({ g, reload }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const http = g.HealthCheckProtocol === "HTTP" || g.HealthCheckProtocol === "HTTPS";
  const [form, setForm] = useState(null);

  const openEdit = () => setForm({
    HealthCheckProtocol: g.HealthCheckProtocol, HealthCheckPort: g.HealthCheckPort, HealthCheckPath: g.HealthCheckPath || "/",
    HealthCheckIntervalSeconds: String(g.HealthCheckIntervalSeconds), HealthCheckTimeoutSeconds: String(g.HealthCheckTimeoutSeconds),
    HealthyThresholdCount: String(g.HealthyThresholdCount), UnhealthyThresholdCount: String(g.UnhealthyThresholdCount),
    Matcher: g.Matcher?.HttpCode || "200",
  });

  return (
    <CapabilityContainer id="ec2.target-groups" title="Health checks" actions={<Button onClick={openEdit}>Edit</Button>}>
      <KeyValue columns={3} items={[
        ["Protocol", g.HealthCheckProtocol], ["Port", g.HealthCheckPort],
        ...(http ? [["Path", g.HealthCheckPath]] : []),
        ["Healthy threshold", g.HealthyThresholdCount], ["Unhealthy threshold", g.UnhealthyThresholdCount],
        ["Timeout", `${g.HealthCheckTimeoutSeconds}s`], ["Interval", `${g.HealthCheckIntervalSeconds}s`],
        ...(http ? [["Success codes", g.Matcher?.HttpCode]] : []),
      ]} />
      <Modal visible={!!form} onDismiss={() => setForm(null)} header="Edit health check" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setForm(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            await api.modifyTargetGroup(g.TargetGroupArn, {
              HealthCheckProtocol: form.HealthCheckProtocol, HealthCheckPort: form.HealthCheckPort, HealthCheckPath: form.HealthCheckPath,
              HealthCheckIntervalSeconds: form.HealthCheckIntervalSeconds, HealthCheckTimeoutSeconds: form.HealthCheckTimeoutSeconds,
              HealthyThresholdCount: form.HealthyThresholdCount, UnhealthyThresholdCount: form.UnhealthyThresholdCount,
              Matcher: { HttpCode: form.Matcher },
            });
            notify.success("Health check settings saved."); setForm(null); reload();
          }}>Save</Button>
        </SpaceBetween></Box>}>
        {form && (
          <SpaceBetween size="l">
            <FormField label="Protocol"><Select selectedOption={opt(form.HealthCheckProtocol)} onChange={({ detail }) => setForm((f) => ({ ...f, HealthCheckProtocol: detail.selectedOption.value }))} options={TG_PROTOCOLS.filter((p) => !["UDP", "TCP_UDP"].includes(p)).map(opt)} ariaLabel="Health check protocol" /></FormField>
            <FormField label="Port"><Input value={form.HealthCheckPort} onChange={({ detail }) => setForm((f) => ({ ...f, HealthCheckPort: detail.value }))} placeholder="traffic-port" ariaLabel="Health check port" /></FormField>
            {(form.HealthCheckProtocol === "HTTP" || form.HealthCheckProtocol === "HTTPS") && (
              <>
                <FormField label="Path"><Input value={form.HealthCheckPath} onChange={({ detail }) => setForm((f) => ({ ...f, HealthCheckPath: detail.value }))} ariaLabel="Health check path" /></FormField>
                <FormField label="Success codes"><Input value={form.Matcher} onChange={({ detail }) => setForm((f) => ({ ...f, Matcher: detail.value }))} placeholder="200" ariaLabel="Success codes" /></FormField>
              </>
            )}
            <FormField label="Healthy threshold"><Input type="number" value={form.HealthyThresholdCount} onChange={({ detail }) => setForm((f) => ({ ...f, HealthyThresholdCount: detail.value }))} ariaLabel="Healthy threshold" /></FormField>
            <FormField label="Unhealthy threshold"><Input type="number" value={form.UnhealthyThresholdCount} onChange={({ detail }) => setForm((f) => ({ ...f, UnhealthyThresholdCount: detail.value }))} ariaLabel="Unhealthy threshold" /></FormField>
            <FormField label="Timeout (seconds)"><Input type="number" value={form.HealthCheckTimeoutSeconds} onChange={({ detail }) => setForm((f) => ({ ...f, HealthCheckTimeoutSeconds: detail.value }))} ariaLabel="Timeout" /></FormField>
            <FormField label="Interval (seconds)"><Input type="number" value={form.HealthCheckIntervalSeconds} onChange={({ detail }) => setForm((f) => ({ ...f, HealthCheckIntervalSeconds: detail.value }))} ariaLabel="Interval" /></FormField>
          </SpaceBetween>
        )}
      </Modal>
    </CapabilityContainer>
  );
}

const TG_ATTR_LABEL = {
  "deregistration_delay.timeout_seconds": "Deregistration delay", "stickiness.enabled": "Stickiness",
  "stickiness.type": "Stickiness type", "stickiness.lb_cookie.duration_seconds": "Stickiness duration",
  "slow_start.duration_seconds": "Slow start duration", "load_balancing.algorithm.type": "Load balancing algorithm",
  "load_balancing.cross_zone.enabled": "Cross-zone load balancing",
};

function AttributesTab({ g }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const t = useAsync(() => api.describeTargetGroupAttributes(g.TargetGroupArn), [g.TargetGroupArn, editing]);
  const attrs = t.data || [];
  const [edited, setEdited] = useState({});

  return (
    <CapabilityContainer id="ec2.target-groups.attributes" title="Attributes"
      actions={<Button onClick={() => { setEdited(Object.fromEntries(attrs.map((a) => [a.Key, a.Value]))); setEditing(true); }}>Edit</Button>}>
      <KeyValue columns={2} items={attrs.map((a) => [TG_ATTR_LABEL[a.Key] || a.Key, a.Value])} />
      <Modal visible={editing} onDismiss={() => setEditing(false)} header="Edit target group attributes" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            await api.modifyTargetGroupAttributes(g.TargetGroupArn, Object.entries(edited).map(([Key, Value]) => ({ Key, Value: String(Value) })));
            notify.success(`Attributes saved.${saveNotice("ec2.target-groups.attributes")}`);
            setEditing(false); t.reload();
          }}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="l">
          {Object.keys(edited).map((k) => (
            <FormField key={k} label={TG_ATTR_LABEL[k] || k}>
              {k.endsWith(".enabled") ? (
                <RadioGroup value={edited[k]} onChange={({ detail }) => setEdited((e) => ({ ...e, [k]: detail.value }))} items={[{ value: "true", label: "Enabled" }, { value: "false", label: "Disabled" }]} />
              ) : (
                <Input value={edited[k]} onChange={({ detail }) => setEdited((e) => ({ ...e, [k]: detail.value }))} ariaLabel={TG_ATTR_LABEL[k] || k} />
              )}
            </FormField>
          ))}
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}

export function CreateTargetGroup() {
  const notify = useNotify();
  const [targetType, setTargetType] = useState("instance");
  const [name, setName] = useState("");
  const [protocol, setProtocol] = useState("HTTP");
  const [protocolVersion, setProtocolVersion] = useState("HTTP1");
  const [port, setPort] = useState("80");
  const [vpcId, setVpcId] = useState("");
  const [hcProtocol, setHcProtocol] = useState("HTTP");
  const [hcPath, setHcPath] = useState("/");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const vpcs = useAsync(() => api.describeVpcs(), []).data || [];
  const http = protocol === "HTTP" || protocol === "HTTPS";

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const g = await api.createTargetGroup({
        Name: name, TargetType: targetType,
        Protocol: targetType === "lambda" ? undefined : protocol,
        ProtocolVersion: targetType !== "lambda" && http ? protocolVersion : undefined,
        Port: targetType === "lambda" ? undefined : port,
        VpcId: targetType === "lambda" ? undefined : vpcId,
        HealthCheckProtocol: targetType === "lambda" ? undefined : hcProtocol,
        HealthCheckPath: hcProtocol === "HTTP" || hcProtocol === "HTTPS" ? hcPath : undefined,
        Tags: tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ Key: t.key, Value: t.value || "" })),
      });
      notify.success(`Target group "${name}" created.`);
      navigate("ec2", "target-groups", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create target group</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "target-groups")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name || (targetType !== "lambda" && !vpcId)} onClick={submit}>Create target group</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Basic configuration</Header>}>
            <SpaceBetween size="l">
              <FormField label="Choose a target type"><RadioGroup value={targetType} onChange={({ detail }) => setTargetType(detail.value)} items={TARGET_TYPES} /></FormField>
              <FormField label="Target group name" constraintText="Alphanumeric characters and hyphens only; cannot begin or end with a hyphen.">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-target-group" ariaLabel="Target group name" />
              </FormField>
              {targetType !== "lambda" && (
                <>
                  <FormField label="Protocol"><Select selectedOption={opt(protocol)} onChange={({ detail }) => setProtocol(detail.selectedOption.value)} options={TG_PROTOCOLS.map(opt)} ariaLabel="Protocol" /></FormField>
                  {http && <FormField label="Protocol version"><Select selectedOption={opt(protocolVersion)} onChange={({ detail }) => setProtocolVersion(detail.selectedOption.value)} options={["HTTP1", "HTTP2", "GRPC"].map(opt)} ariaLabel="Protocol version" /></FormField>}
                  <FormField label="Port"><Input type="number" value={port} onChange={({ detail }) => setPort(detail.value)} ariaLabel="Port" /></FormField>
                  <FormField label="VPC"><Select selectedOption={vpcId ? opt(vpcId) : null} onChange={({ detail }) => setVpcId(detail.selectedOption.value)}
                    options={vpcs.map((v) => opt(v.vpcId, `${v.vpcId}${v.isDefault === "true" ? " (default)" : ""}`))} placeholder="Select a VPC" ariaLabel="VPC" /></FormField>
                </>
              )}
            </SpaceBetween>
          </Container>
          {targetType !== "lambda" && (
            <Container header={<Header variant="h2">Health checks</Header>}>
              <SpaceBetween size="l">
                <FormField label="Health check protocol"><Select selectedOption={opt(hcProtocol)} onChange={({ detail }) => setHcProtocol(detail.selectedOption.value)} options={TG_PROTOCOLS.filter((p) => !["UDP", "TCP_UDP"].includes(p)).map(opt)} ariaLabel="Health check protocol" /></FormField>
                {(hcProtocol === "HTTP" || hcProtocol === "HTTPS") && <FormField label="Health check path"><Input value={hcPath} onChange={({ detail }) => setHcPath(detail.value)} ariaLabel="Health check path" /></FormField>}
              </SpaceBetween>
            </Container>
          )}
          <Container header={<Header variant="h2">Tags - optional</Header>}><FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
