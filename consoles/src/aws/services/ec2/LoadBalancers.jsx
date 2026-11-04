/* EC2 console → Load Balancing → Load balancers. Native wire: core/elbv2_core.py's
 * Query-protocol engine (separate "elasticloadbalancing" AWS service, same /_wire). */
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
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import { opt, ALB_PROTOCOLS, NLB_PROTOCOLS, ElbTagsTab } from "./elbv2-shared.jsx";
import * as api from "./api.js";

const typeLabel = (t) => (t === "application" ? "Application" : t === "network" ? "Network" : "Gateway");

export function LoadBalancers() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeLoadBalancers(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Load balancers</Header>}>
      <ResourceTable
        resourceName="Load Balancers"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="LoadBalancerArn"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find load balancers by attribute or tag"
        empty={{ title: "No load balancers", subtitle: "You don't have any load balancers configured." }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (lb) => <Link href={href("ec2", "load-balancers", lb.LoadBalancerName)} onFollow={follow}>{lb.LoadBalancerName}</Link> },
          { id: "dns", header: "DNS name", cell: (lb) => lb.DNSName },
          { id: "state", header: "State", cell: (lb) => lb.State?.Code },
          { id: "vpc", header: "VPC ID", cell: (lb) => lb.VpcId },
          { id: "az", header: "Availability Zones", cell: (lb) => lb.AvailabilityZones.map((a) => a.ZoneName).join(", ") },
          { id: "type", header: "Type", cell: (lb) => typeLabel(lb.Type) },
          { id: "created", header: "Date created", cell: (lb) => fmtDate(lb.CreatedTime) },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "view", text: "View details", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "view") navigate("ec2", "load-balancers", sel[0].LoadBalancerName);
              else setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-load-balancer")} onFollow={follow}>Create load balancer</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="load balancer" names={sel.map((lb) => lb.LoadBalancerName)} onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const lb of sel) await api.deleteLoadBalancer(lb.LoadBalancerArn); notify.success(`${sel.length} load balancer(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function LoadBalancerDetail({ params }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeLoadBalancers({ Names: [params.id] }).then((xs) => xs[0]), [params.id]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Load balancer not found" }} />;
  const lb = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[{ id: "delete", text: "Delete load balancer" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
    }>{lb.LoadBalancerName}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["DNS name", lb.DNSName], ["State", lb.State?.Code], ["Type", typeLabel(lb.Type)], ["Scheme", lb.Scheme],
          ["VPC ID", lb.VpcId], ["Availability Zones", lb.AvailabilityZones.map((a) => a.ZoneName).join(", ")],
          ["Subnets", lb.AvailabilityZones.map((a) => a.SubnetId).join(", ")], ["IP address type", lb.IpAddressType],
          ["Hosted zone", lb.CanonicalHostedZoneId], ["Date created", fmtDate(lb.CreatedTime)],
        ]} />
        <Tabs tabs={[
          { id: "listeners", label: "Listeners and rules", content: <ListenersTab lb={lb} /> },
          { id: "monitoring", label: "Monitoring", content: <CapabilityContainer id="ec2.load-balancing.monitoring" title="CloudWatch metrics" /> },
          { id: "security", label: "Security", content: <SecurityGroupsTab lb={lb} reload={t.reload} /> },
          { id: "attributes", label: "Attributes", content: <AttributesTab lb={lb} /> },
          { id: "tags", label: "Tags", content: <ElbTagsTab arn={lb.LoadBalancerArn} /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={del} resourceType="load balancer" names={[lb.LoadBalancerName]} onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteLoadBalancer(lb.LoadBalancerArn); notify.success("Load balancer deleted."); navigate("ec2", "load-balancers"); }} />
    </ContentLayout>
  );
}

function actionSummary(a) {
  if (a.Type === "forward") {
    const tgs = a.ForwardConfig?.TargetGroups?.member ? [].concat(a.ForwardConfig.TargetGroups.member) : [];
    return "Forward to " + (tgs.map((x) => x.TargetGroupArn?.split("/")[1]).join(", ") || a.TargetGroupArn?.split("/")[1] || "target group");
  }
  if (a.Type === "redirect") return `Redirect to ${a.RedirectConfig?.StatusCode}`;
  if (a.Type === "fixed-response") return `Fixed response ${a.FixedResponseConfig?.StatusCode}`;
  return a.Type;
}

function ListenersTab({ lb }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [adding, setAdding] = useState(false);
  const [viewing, setViewing] = useState(null);
  const t = useAsync(() => api.describeListeners({ LoadBalancerArn: lb.LoadBalancerArn }), [lb.LoadBalancerArn]);
  const rows = t.data || [];
  const protocols = lb.Type === "application" ? ALB_PROTOCOLS : NLB_PROTOCOLS;

  if (viewing) return <RulesPanel listener={viewing} onBack={() => { setViewing(null); t.reload(); }} />;

  return (
    <SpaceBetween size="l">
      <Table
        items={rows}
        loading={t.loading}
        trackBy="ListenerArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { await api.deleteListener(sel[0].ListenerArn); notify.success("Listener deleted."); setSel([]); t.reload(); }}>Delete</Button>
            <Button disabled={sel.length !== 1} onClick={() => setViewing(sel[0])}>View/edit rules</Button>
            <Button variant="primary" onClick={() => setAdding(true)}>Add listener</Button>
          </SpaceBetween>
        }>Listeners</Header>}
        columnDefinitions={[
          { id: "pp", header: "Listener", isRowHeader: true, cell: (l) => `${l.Protocol || "GENEVE"}:${l.Port ?? "-"}` },
          { id: "act", header: "Default action", cell: (l) => actionSummary(l.DefaultActions[0]) },
          { id: "ssl", header: "SSL policy", cell: (l) => l.SslPolicy || "-" },
        ]}
        empty={<Box textAlign="center" color="inherit">This load balancer has no listeners.</Box>}
      />
      <AddListenerModal visible={adding} lb={lb} protocols={protocols} onDismiss={() => setAdding(false)} onCreated={() => { setAdding(false); t.reload(); }} />
    </SpaceBetween>
  );
}

function AddListenerModal({ visible, lb, protocols, onDismiss, onCreated }) {
  const notify = useNotify();
  const [protocol, setProtocol] = useState(protocols[0]);
  const [port, setPort] = useState(protocol === "HTTPS" ? "443" : "80");
  const [cert, setCert] = useState("");
  const [targetGroupArn, setTargetGroupArn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const tgs = useAsync(() => api.describeTargetGroups(), [visible]).data || [];
  const needsCert = protocol === "HTTPS" || protocol === "TLS";

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createListener({
        LoadBalancerArn: lb.LoadBalancerArn, Protocol: protocol, Port: port,
        Certificates: needsCert ? [{ CertificateArn: cert }] : undefined,
        DefaultActions: [{ Type: "forward", TargetGroupArn: targetGroupArn }],
      });
      notify.success(`Listener ${protocol}:${port} created.`);
      onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Add listener" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!port || !targetGroupArn || (needsCert && !cert)} onClick={submit}>Add</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Protocol"><Select selectedOption={opt(protocol)} onChange={({ detail }) => { setProtocol(detail.selectedOption.value); setPort(detail.selectedOption.value === "HTTPS" ? "443" : "80"); }} options={protocols.map(opt)} ariaLabel="Protocol" /></FormField>
        <FormField label="Port"><Input type="number" value={port} onChange={({ detail }) => setPort(detail.value)} ariaLabel="Port" /></FormField>
        {needsCert && <FormField label="Default SSL/TLS certificate (ARN)" description="Vyomi stores the ARN but does not validate certificate contents.">
          <Input value={cert} onChange={({ detail }) => setCert(detail.value)} placeholder="arn:aws:acm:us-east-1:123456789012:certificate/..." ariaLabel="Certificate ARN" />
        </FormField>}
        <FormField label="Default action — forward to"><Select selectedOption={targetGroupArn ? opt(targetGroupArn, tgs.find((g) => g.TargetGroupArn === targetGroupArn)?.TargetGroupName) : null}
          onChange={({ detail }) => setTargetGroupArn(detail.selectedOption.value)} options={tgs.map((g) => opt(g.TargetGroupArn, g.TargetGroupName))}
          placeholder="Select a target group" ariaLabel="Default action target group" empty="No target groups — create one first" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

const COND_LABEL = { "path-pattern": "Path pattern", "host-header": "Host header" };

function RulesPanel({ listener, onBack }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [adding, setAdding] = useState(false);
  const t = useAsync(() => api.describeRules({ ListenerArn: listener.ListenerArn }), [listener.ListenerArn]);
  const rows = t.data || [];
  const tgs = useAsync(() => api.describeTargetGroups(), []).data || [];

  return (
    <SpaceBetween size="l">
      <Button iconName="angle-left" onClick={onBack}>Back to listeners</Button>
      <Table
        items={rows}
        loading={t.loading}
        trackBy="RuleArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems.filter((r) => !r.IsDefault))}
        header={<Header variant="h2" counter={`(${rows.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { await api.deleteRule(sel[0].RuleArn); notify.success("Rule deleted."); setSel([]); t.reload(); }}>Delete</Button>
            <Button variant="primary" onClick={() => setAdding(true)}>Add rule</Button>
          </SpaceBetween>
        }>{`Rules for ${listener.Protocol || "GENEVE"}:${listener.Port ?? "-"}`}</Header>}
        columnDefinitions={[
          { id: "prio", header: "Priority", isRowHeader: true, cell: (r) => (r.IsDefault ? "Default" : r.Priority) },
          { id: "cond", header: "IF", cell: (r) => (r.Conditions.length ? r.Conditions.map((c) => `${COND_LABEL[c.Field] || c.Field}: ${(c.Values || []).join(", ")}`).join(" AND ") : "-") },
          { id: "act", header: "THEN", cell: (r) => actionSummary(r.Actions[0]) },
        ]}
        empty={<Box textAlign="center" color="inherit">No rules.</Box>}
      />
      <AddRuleModal visible={adding} listener={listener} tgs={tgs} onDismiss={() => setAdding(false)} onCreated={() => { setAdding(false); t.reload(); }} />
    </SpaceBetween>
  );
}

function AddRuleModal({ visible, listener, tgs, onDismiss, onCreated }) {
  const notify = useNotify();
  const [priority, setPriority] = useState("10");
  const [condField, setCondField] = useState("path-pattern");
  const [condValue, setCondValue] = useState("/images/*");
  const [targetGroupArn, setTargetGroupArn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createRule({
        ListenerArn: listener.ListenerArn, Priority: priority,
        Conditions: [{ Field: condField, Values: condValue.split(",").map((v) => v.trim()).filter(Boolean) }],
        Actions: [{ Type: "forward", TargetGroupArn: targetGroupArn }],
      });
      notify.success(`Rule (priority ${priority}) created.`);
      onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Add rule" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!priority || !condValue || !targetGroupArn} onClick={submit}>Add rule</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Priority"><Input type="number" value={priority} onChange={({ detail }) => setPriority(detail.value)} ariaLabel="Priority" /></FormField>
        <FormField label="Condition"><Select selectedOption={opt(condField, COND_LABEL[condField])} onChange={({ detail }) => setCondField(detail.selectedOption.value)}
          options={Object.entries(COND_LABEL).map(([value, label]) => opt(value, label))} ariaLabel="Condition field" /></FormField>
        <FormField label={condField === "path-pattern" ? "Path patterns (comma-separated)" : "Host headers (comma-separated)"}>
          <Input value={condValue} onChange={({ detail }) => setCondValue(detail.value)} ariaLabel="Condition value" />
        </FormField>
        <FormField label="Forward to"><Select selectedOption={targetGroupArn ? opt(targetGroupArn, tgs.find((g) => g.TargetGroupArn === targetGroupArn)?.TargetGroupName) : null}
          onChange={({ detail }) => setTargetGroupArn(detail.selectedOption.value)} options={tgs.map((g) => opt(g.TargetGroupArn, g.TargetGroupName))}
          placeholder="Select a target group" ariaLabel="Forward to target group" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

function SecurityGroupsTab({ lb, reload }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const allSgs = useAsync(() => api.describeSecurityGroups(), [editing]).data || [];
  const [picked, setPicked] = useState([]);
  const current = lb.SecurityGroups || [];

  return (
    <Container header={<Header variant="h2" actions={<Button onClick={() => { setPicked(allSgs.filter((g) => current.includes(g.GroupId)).map((g) => opt(g.GroupId, `${g.GroupName} (${g.GroupId})`))); setEditing(true); }}>Edit security groups</Button>}>Security groups</Header>}>
      {current.length ? (
        <Table variant="embedded" items={current.map((id) => ({ id }))} columnDefinitions={[{ id: "sg", header: "Security group ID", cell: (r) => r.id }]} />
      ) : <Box color="text-body-secondary">No security groups attached.</Box>}
      <Modal visible={editing} onDismiss={() => setEditing(false)} header="Edit security groups"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { await api.setSecurityGroups(lb.LoadBalancerArn, picked.map((p) => p.value)); notify.success("Security groups updated."); setEditing(false); reload(); }}>Save</Button>
        </SpaceBetween></Box>}>
        <FormField label="Security groups"><Multiselect selectedOptions={picked} onChange={({ detail }) => setPicked(detail.selectedOptions)}
          options={allSgs.map((g) => opt(g.GroupId, `${g.GroupName} (${g.GroupId})`))} placeholder="Choose security groups" ariaLabel="Security groups" /></FormField>
      </Modal>
    </Container>
  );
}

const LB_ATTR_LABEL = {
  "idle_timeout.timeout_seconds": "Idle timeout", "deletion_protection.enabled": "Deletion protection",
  "routing.http2.enabled": "HTTP/2", "routing.http.drop_invalid_header_fields.enabled": "Drop invalid header fields",
  "routing.http.xff_client_port.enabled": "X-Forwarded-For port preservation", "routing.http.desync_mitigation_mode": "Desync mitigation mode",
  "waf.fail_open.enabled": "WAF fail open", "load_balancing.cross_zone.enabled": "Cross-zone load balancing",
  "access_logs.s3.enabled": "Access logs", "access_logs.s3.bucket": "Access logs S3 bucket", "access_logs.s3.prefix": "Access logs S3 prefix",
};

function AttributesTab({ lb }) {
  const notify = useNotify();
  const [editing, setEditing] = useState(false);
  const t = useAsync(() => api.describeLoadBalancerAttributes(lb.LoadBalancerArn), [lb.LoadBalancerArn, editing]);
  const attrs = t.data || [];
  const [edited, setEdited] = useState({});

  return (
    <CapabilityContainer id="ec2.load-balancers.attributes" title="Attributes"
      actions={<Button onClick={() => { setEdited(Object.fromEntries(attrs.map((a) => [a.Key, a.Value]))); setEditing(true); }}>Edit</Button>}>
      <KeyValue columns={2} items={attrs.map((a) => [LB_ATTR_LABEL[a.Key] || a.Key, a.Value])} />
      <Modal visible={editing} onDismiss={() => setEditing(false)} header="Edit load balancer attributes" size="large"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            await api.modifyLoadBalancerAttributes(lb.LoadBalancerArn, Object.entries(edited).map(([Key, Value]) => ({ Key, Value: String(Value) })));
            notify.success(`Attributes saved.${saveNotice("ec2.load-balancers.attributes")}`);
            setEditing(false); t.reload();
          }}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="l">
          {Object.keys(edited).map((k) => (
            <FormField key={k} label={LB_ATTR_LABEL[k] || k}>
              {k.endsWith(".enabled") ? (
                <RadioGroup value={edited[k]} onChange={({ detail }) => setEdited((e) => ({ ...e, [k]: detail.value }))} items={[{ value: "true", label: "Enabled" }, { value: "false", label: "Disabled" }]} />
              ) : (
                <Input value={edited[k]} onChange={({ detail }) => setEdited((e) => ({ ...e, [k]: detail.value }))} ariaLabel={LB_ATTR_LABEL[k] || k} />
              )}
            </FormField>
          ))}
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}

export function CreateLoadBalancer() {
  const notify = useNotify();
  const [type, setType] = useState("application");
  const [name, setName] = useState("");
  const [scheme, setScheme] = useState("internet-facing");
  const [ipType, setIpType] = useState("ipv4");
  const [vpcId, setVpcId] = useState("");
  const [subnetIds, setSubnetIds] = useState([]);
  const [sgIds, setSgIds] = useState([]);
  const [protocol, setProtocol] = useState("HTTP");
  const [port, setPort] = useState("80");
  const [cert, setCert] = useState("");
  const [targetGroupArn, setTargetGroupArn] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const vpcs = useAsync(() => api.describeVpcs(), []).data || [];
  const subnets = useAsync(() => api.describeSubnets(), []).data || [];
  const sgs = useAsync(() => api.describeSecurityGroups(), []).data || [];
  const tgs = useAsync(() => api.describeTargetGroups(), []).data || [];
  const protocols = type === "application" ? ALB_PROTOCOLS : NLB_PROTOCOLS;
  const vpcSubnets = subnets.filter((s) => s.vpcId === vpcId);
  const needsCert = protocol === "HTTPS" || protocol === "TLS";

  const setLbType = (v) => { setType(v); setProtocol(v === "application" ? "HTTP" : "TCP"); setPort(v === "application" ? "80" : "80"); };

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const lb = await api.createLoadBalancer({
        Name: name, Type: type, Scheme: scheme, IpAddressType: ipType,
        Subnets: subnetIds, SecurityGroups: type === "application" ? sgIds : (sgIds.length ? sgIds : undefined),
        Tags: tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ Key: t.key, Value: t.value || "" })),
      });
      if (targetGroupArn) {
        await api.createListener({
          LoadBalancerArn: lb.LoadBalancerArn, Protocol: protocol, Port: port,
          Certificates: needsCert ? [{ CertificateArn: cert }] : undefined,
          DefaultActions: [{ Type: "forward", TargetGroupArn: targetGroupArn }],
        });
      }
      notify.success(`Load balancer "${name}" created.`);
      navigate("ec2", "load-balancers", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const minSubnets = type === "application" ? 2 : 1;

  return (
    <ContentLayout header={<Header variant="h1">Create load balancer</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "load-balancers")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name || subnetIds.length < minSubnets || !vpcId} onClick={submit}>Create load balancer</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Load balancer type</Header>}>
            <RadioGroup value={type} onChange={({ detail }) => setLbType(detail.value)} items={[
              { value: "application", label: "Application Load Balancer", description: "Best suited for load balancing of HTTP and HTTPS traffic." },
              { value: "network", label: "Network Load Balancer", description: "Best suited for load balancing of TCP, UDP and TLS traffic." },
            ]} />
          </Container>
          <Container header={<Header variant="h2">Basic configuration</Header>}>
            <SpaceBetween size="l">
              <FormField label="Load balancer name" constraintText="Alphanumeric characters and hyphens only; cannot begin or end with a hyphen.">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-load-balancer" ariaLabel="Load balancer name" />
              </FormField>
              <FormField label="Scheme"><RadioGroup value={scheme} onChange={({ detail }) => setScheme(detail.value)} items={[
                { value: "internet-facing", label: "Internet-facing" }, { value: "internal", label: "Internal" },
              ]} /></FormField>
              <FormField label="IP address type"><RadioGroup value={ipType} onChange={({ detail }) => setIpType(detail.value)} items={[
                { value: "ipv4", label: "IPv4" }, { value: "dualstack", label: "Dualstack" },
              ]} /></FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Network mapping</Header>}>
            <SpaceBetween size="l">
              <FormField label="VPC"><Select selectedOption={vpcId ? opt(vpcId) : null} onChange={({ detail }) => { setVpcId(detail.selectedOption.value); setSubnetIds([]); }}
                options={vpcs.map((v) => opt(v.vpcId, `${v.vpcId}${v.isDefault === "true" ? " (default)" : ""}`))} placeholder="Select a VPC" ariaLabel="VPC" /></FormField>
              <FormField label="Mappings" description={`Select at least ${minSubnets} subnet${minSubnets > 1 ? "s" : ""} in different Availability Zones.`}>
                <Multiselect selectedOptions={vpcSubnets.filter((s) => subnetIds.includes(s.subnetId)).map((s) => opt(s.subnetId, `${s.availabilityZone} / ${s.subnetId}`))}
                  onChange={({ detail }) => setSubnetIds(detail.selectedOptions.map((o) => o.value))}
                  options={vpcSubnets.map((s) => opt(s.subnetId, `${s.availabilityZone} / ${s.subnetId}`))}
                  disabled={!vpcId} placeholder="Select subnets" ariaLabel="Subnet mappings" />
              </FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Security groups</Header>}>
            <FormField label="Security groups"><Multiselect selectedOptions={sgs.filter((g) => sgIds.includes(g.GroupId)).map((g) => opt(g.GroupId, `${g.GroupName} (${g.GroupId})`))}
              onChange={({ detail }) => setSgIds(detail.selectedOptions.map((o) => o.value))}
              options={sgs.map((g) => opt(g.GroupId, `${g.GroupName} (${g.GroupId})`))} placeholder="Select existing security group" ariaLabel="Security groups" /></FormField>
          </Container>
          <Container header={<Header variant="h2">Listeners and routing</Header>}>
            <SpaceBetween size="l">
              <FormField label="Protocol"><Select selectedOption={opt(protocol)} onChange={({ detail }) => { setProtocol(detail.selectedOption.value); setPort(detail.selectedOption.value === "HTTPS" ? "443" : "80"); }} options={protocols.map(opt)} ariaLabel="Protocol" /></FormField>
              <FormField label="Port"><Input type="number" value={port} onChange={({ detail }) => setPort(detail.value)} ariaLabel="Port" /></FormField>
              {needsCert && <FormField label="Default SSL/TLS certificate (ARN)"><Input value={cert} onChange={({ detail }) => setCert(detail.value)} placeholder="arn:aws:acm:us-east-1:123456789012:certificate/..." ariaLabel="Certificate ARN" /></FormField>}
              <FormField label="Default action" description="Forward to a target group.">
                <Select selectedOption={targetGroupArn ? opt(targetGroupArn, tgs.find((g) => g.TargetGroupArn === targetGroupArn)?.TargetGroupName) : null}
                  onChange={({ detail }) => setTargetGroupArn(detail.selectedOption.value)} options={tgs.map((g) => opt(g.TargetGroupArn, g.TargetGroupName))}
                  placeholder="Select a target group" ariaLabel="Default action target group" empty="No target groups yet" />
              </FormField>
              <Link href={href("ec2", "create-target-group")} onFollow={follow}>Create target group</Link>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}><FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField></Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
