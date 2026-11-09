/* Amazon EKS console: clusters list, create-cluster form, cluster detail (Overview, Compute, Networking, Add-ons, Access, Observability,
 * Update history, Tags, Backup & kubectl). Every action is a call on the native EKS REST wire (core/aws_eks_core.py, backed by a real k3s API server). */
import { useEffect, useMemo, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Multiselect from "@cloudscape-design/components/multiselect";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import { awsQuery } from "../../../common/wire.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate, useRoute } from "../../../common/router.js";
import BackupTab from "./BackupTab.jsx";
import * as api from "./api.js";

const VERSIONS = ["1.34", "1.33", "1.32", "1.31", "1.30"];
const LOG_TYPES = ["api", "audit", "authenticator", "controllerManager", "scheduler"];
const BUSY = /CREATING|UPDATING|DELETING/;
const stat = (s) => <StatusIndicator type={s === "ACTIVE" || s === "Successful" ? "success" : /FAILED|Failed|DEGRADED/.test(s) ? "error" : /Cancel/.test(s) ? "stopped" : "in-progress"}>{s}</StatusIndicator>;
const opt = (v) => (v ? { label: v, value: v } : null);

/** Re-run `reload` every `ms` while `active`. */
function usePoll(reload, active, ms = 3000) {
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(reload, ms);
    return () => clearInterval(t);
  }, [reload, active, ms]);
}

/* ── Clusters list ─────────────────────────────────────────────────────────── */
export function Clusters() {
  const notify = useNotify();
  const t = useAsync(() => api.listClusters(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  usePoll(t.reload, (t.data || []).some((c) => BUSY.test(c.status)));
  return (
    <>
      <ResourceTable resourceName="Clusters" items={t.data || []} loading={t.loading && !t.data} error={t.error} onRefresh={t.reload} trackBy="name"
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Filter clusters"
        empty={{ title: "No clusters", subtitle: "You don't have any clusters in this Region.", action: <Button variant="primary" onClick={() => navigate("eks", "create")}>Create cluster</Button> }}
        columns={[
          { id: "n", header: "Cluster name", isRowHeader: true, sortingField: "name", cell: (c) => <Link href={`#/eks/clusters/view?name=${encodeURIComponent(c.name)}`} onFollow={follow}>{c.name}</Link> },
          { id: "s", header: "Status", sortingField: "status", cell: (c) => stat(c.status) },
          { id: "v", header: "Kubernetes version", sortingField: "version", cell: (c) => c.version },
          { id: "p", header: "Provider", cell: () => "EKS" },
          { id: "c", header: "Created", cell: (c) => fmtDate(c.createdAt) },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={() => { location.hash = `#/eks/clusters/view?name=${encodeURIComponent(sel[0].name)}`; }}>View details</Button>
          <Button disabled={!sel.length || sel[0].status === "DELETING"} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => navigate("eks", "create")}>Create cluster</Button>
        </SpaceBetween>} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="cluster" names={sel.map((c) => c.name)}
        onConfirm={async () => { await api.deleteCluster(sel[0].name); notify.success(`Deleting cluster "${sel[0].name}".`); setSel([]); t.reload(); }} />
    </>
  );
}

/* ── Create cluster ────────────────────────────────────────────────────────── */
export function CreateCluster() {
  const notify = useNotify();
  const roles = useAsync(() => api.listRoles(), []);
  const subnets = useAsync(() => api.listSubnets(), []);
  const sgs = useAsync(() => api.listSecurityGroups(), []);
  const [f, setF] = useState({ name: "", version: VERSIONS[1], role: null, subnets: [], sgs: [], access: "public", mode: "API_AND_CONFIG_MAP", logs: [] });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((o) => ({ ...o, [k]: v }));
  const vpcOf = Object.fromEntries((subnets.data || []).map((s) => [s.id, s.vpc]));
  const prep = async () => {
    setErr(null);
    try {
      const arn = await api.ensureRole("eksClusterRole", "eks.amazonaws.com");
      roles.reload(); set("role", { label: "eksClusterRole", value: arn });
    } catch (e) { setErr(e); }
  };
  const prepNet = async () => {
    setErr(null);
    try {
      const v = (await awsQuery("ec2", "CreateVpc", { CidrBlock: "10.0.0.0/16" })).CreateVpcResponse.vpc.vpcId;
      for (const [i, az] of [[1, "a"], [2, "b"]]) await awsQuery("ec2", "CreateSubnet", { VpcId: v, CidrBlock: `10.0.${i}.0/24`, AvailabilityZone: `us-east-1${az}` });
      subnets.reload();
    } catch (e) { setErr(e); }
  };
  const go = async () => {
    setErr(null); setBusy(true);
    try {
      const body = { name: f.name, version: f.version, roleArn: f.role?.value,
        resourcesVpcConfig: { subnetIds: f.subnets.map((s) => s.value), securityGroupIds: f.sgs.map((s) => s.value), endpointPublicAccess: f.access !== "private", endpointPrivateAccess: f.access !== "public" },
        accessConfig: { authenticationMode: f.mode, bootstrapClusterCreatorAdminPermissions: true } };
      if (f.logs.length) body.logging = { clusterLogging: [{ types: f.logs, enabled: true }] };
      await api.createCluster(body);
      notify.success(`Cluster "${f.name}" is being created.`);
      location.hash = `#/eks/clusters/view?name=${encodeURIComponent(f.name)}`;
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const subOpts = (subnets.data || []).map((s) => ({ label: s.id, value: s.id, description: `${s.az} · ${s.cidr} · ${s.vpc}` }));
  const chosenVpc = new Set(f.subnets.map((s) => vpcOf[s.value]));
  return (
    <ContentLayout header={<Header variant="h1" description="A real Kubernetes control plane (k3s) is started for the cluster; it is ACTIVE when its API server answers.">Create EKS cluster</Header>}>
      <SpaceBetween size="l">
        <ErrorAlert error={err} header="Could not create the cluster" />
        <CapabilityContainer id="eks.cluster.lifecycle" title="Cluster configuration">
          <SpaceBetween size="m">
            <FormField label="Name" description="Letters, digits, hyphens and underscores; starts with a letter or digit." constraintText="1-100 characters"><Input value={f.name} onChange={({ detail }) => set("name", detail.value)} ariaLabel="Cluster name" placeholder="my-cluster" /></FormField>
            <FormField label="Kubernetes version"><Select selectedOption={opt(f.version)} onChange={({ detail }) => set("version", detail.selectedOption.value)} options={VERSIONS.map(opt)} ariaLabel="Kubernetes version" /></FormField>
            <FormField label="Cluster service role" description="The IAM role EKS uses to manage the cluster."
              secondaryControl={<Button onClick={prep} iconName="add-plus" ariaLabel="Create recommended role">Create recommended role</Button>}>
              <Select selectedOption={f.role} onChange={({ detail }) => set("role", detail.selectedOption)} options={(roles.data || []).map((r) => ({ label: r.name, value: r.arn, description: r.arn }))} placeholder="Choose a role" empty="No IAM roles" ariaLabel="Cluster service role" />
            </FormField>
          </SpaceBetween>
        </CapabilityContainer>
        <Container header={<Header variant="h2">Networking</Header>}>
          <SpaceBetween size="m">
            <FormField label="Subnets" description="Select subnets in at least two Availability Zones of one VPC."
              secondaryControl={<Button onClick={prepNet} iconName="add-plus">Create VPC with 2 subnets</Button>}
              errorText={chosenVpc.size > 1 ? "Subnets must belong to the same VPC." : undefined}>
              <Multiselect selectedOptions={f.subnets} onChange={({ detail }) => set("subnets", detail.selectedOptions)} options={subOpts} placeholder="Choose subnets" empty="No subnets" ariaLabel="Subnets" />
            </FormField>
            <FormField label="Security groups (optional)"><Multiselect selectedOptions={f.sgs} onChange={({ detail }) => set("sgs", detail.selectedOptions)} options={(sgs.data || []).map((s) => ({ label: s.id, value: s.id, description: s.name }))} placeholder="Choose security groups" ariaLabel="Security groups" /></FormField>
            <FormField label="Cluster endpoint access">
              <RadioGroup value={f.access} onChange={({ detail }) => set("access", detail.value)} items={[{ value: "public", label: "Public" }, { value: "public-private", label: "Public and private" }, { value: "private", label: "Private" }]} />
            </FormField>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2">Cluster access</Header>}>
          <FormField label="Authentication mode" description="Access entries need API or API_AND_CONFIG_MAP."><Select selectedOption={opt(f.mode)} onChange={({ detail }) => set("mode", detail.selectedOption.value)} options={["API_AND_CONFIG_MAP", "API", "CONFIG_MAP"].map(opt)} /></FormField>
        </Container>
        <CapabilityContainer id="eks.logging" title="Control plane logging">
          <SpaceBetween size="xs">{LOG_TYPES.map((t) => <Checkbox key={t} checked={f.logs.includes(t)} onChange={({ detail }) => set("logs", detail.checked ? [...f.logs, t] : f.logs.filter((x) => x !== t))}>{t}</Checkbox>)}</SpaceBetween>
        </CapabilityContainer>
        <Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" href="#/eks/clusters" onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!f.name || !f.role || f.subnets.length < 2 || chosenVpc.size > 1} onClick={go}>Create</Button>
        </SpaceBetween></Box>
      </SpaceBetween>
    </ContentLayout>
  );
}

/* ── Cluster detail ────────────────────────────────────────────────────────── */
export function ClusterDetail() {
  const notify = useNotify();
  const { query } = useRoute();
  const name = query.name;
  const c = useAsync(() => api.describeCluster(name), [name]);
  const [upg, setUpg] = useState(false);
  const [del, setDel] = useState(false);
  const x = c.data;
  usePoll(c.reload, x && BUSY.test(x.status));
  const nextVersions = x ? VERSIONS.filter((v) => VERSIONS.indexOf(v) === VERSIONS.indexOf(x.version) - 1) : [];
  return (
    <ContentLayout header={
      <Header variant="h1" info={x && stat(x.status)} actions={<SpaceBetween direction="horizontal" size="xs">
        <Button onClick={c.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button disabled={!x || x.status !== "ACTIVE" || !nextVersions.length} onClick={() => setUpg(true)}>Upgrade version</Button>
        <Button disabled={!x || x.status === "DELETING"} onClick={() => setDel(true)}>Delete cluster</Button>
      </SpaceBetween>}>{name}</Header>}>
      <SpaceBetween size="l">
        <ErrorAlert error={c.error} />
        {x?.status === "CREATING" && <Alert type="info" header="Cluster is being created">Starting the Kubernetes control plane. The first start pulls nothing from the internet but can take a minute.</Alert>}
        {x?.status === "FAILED" && <Alert type="error" header="Cluster creation failed">{x.health?.issues?.[0]?.message}</Alert>}
        {x && (
          <Tabs tabs={[
            { id: "overview", label: "Overview", content: <Overview x={x} /> },
            { id: "compute", label: "Compute", content: <Compute x={x} /> },
            { id: "networking", label: "Networking", content: <Networking x={x} reload={c.reload} /> },
            { id: "addons", label: "Add-ons", content: <Addons x={x} /> },
            { id: "access", label: "Access", content: <Access x={x} /> },
            { id: "observability", label: "Observability", content: <Observability x={x} reload={c.reload} /> },
            { id: "updates", label: "Update history", content: <Updates x={x} /> },
            { id: "tags", label: "Tags", content: <Tags arn={x.arn} /> },
            { id: "backup", label: "Backup and kubectl", content: <BackupTab cluster={x} /> },
          ]} />)}
      </SpaceBetween>
      <UpgradeModal visible={upg} x={x} versions={nextVersions} onDismiss={() => setUpg(false)} onDone={() => { notify.success("Cluster version update started."); c.reload(); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="cluster" names={[name]}
        warning="Node groups and Fargate profiles must be deleted first."
        onConfirm={async () => { await api.deleteCluster(name); notify.success(`Deleting cluster "${name}".`); navigate("eks", "clusters"); }} />
    </ContentLayout>
  );
}

function UpgradeModal({ visible, x, versions, onDismiss, onDone }) {
  const [v, setV] = useState(null);
  const [err, setErr] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Upgrade cluster version"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!v} onClick={async () => { try { await api.updateClusterVersion(x.name, v.value); onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Update</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <Box>Current version <b>{x?.version}</b>. EKS upgrades one minor version at a time.</Box>
        <FormField label="Upgrade to"><Select selectedOption={v} onChange={({ detail }) => setV(detail.selectedOption)} options={versions.map(opt)} placeholder="Choose a version" ariaLabel="Upgrade to" /></FormField></SpaceBetween>
    </Modal>
  );
}

function Overview({ x }) {
  const cmd = `aws eks update-kubeconfig --name ${x.name} --region ${x.arn.split(":")[3]}`;
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="eks.cluster.lifecycle" title="Details">
        <ColumnLayout columns={3} variant="text-grid">
          {[["Status", stat(x.status)], ["Kubernetes version", x.version], ["Platform version", x.platformVersion], ["Provider", "EKS"], ["Created", fmtDate(x.createdAt)], ["Cluster IAM role ARN", x.roleArn],
            ["API server endpoint", x.endpoint || "-"], ["OpenID Connect provider URL", x.identity?.oidc?.issuer], ["Cluster ARN", x.arn],
            ["Authentication mode", x.accessConfig?.authenticationMode], ["Support type", x.upgradePolicy?.supportType], ["Service IPv4 range", x.kubernetesNetworkConfig?.serviceIpv4Cidr]].map(([l, v]) => (
            <div key={l}><Box variant="awsui-key-label">{l}</Box><div style={{ wordBreak: "break-all" }}>{v === undefined || v === "" ? "-" : v}</div></div>))}
        </ColumnLayout>
      </CapabilityContainer>
      <Container header={<Header variant="h2" description="Run on your own machine to point kubectl at this cluster.">Connect</Header>}>
        <SpaceBetween size="s">
          <Box variant="code" data-testid="update-kubeconfig"><pre style={{ margin: 0 }}>{cmd}</pre></Box>
          <Box variant="small" color="text-body-secondary">The kubeconfig it writes uses an exec plugin (<code>aws eks get-token</code>), the same flow as Amazon EKS. Use the "Backup and kubectl" tab for a terminal on this cluster.</Box>
        </SpaceBetween>
      </Container>
      <KeyValue title="Certificate authority" columns={1} items={[["certificateAuthority.data (base64 PEM)", x.certificateAuthority?.data ? <code style={{ wordBreak: "break-all", fontSize: 11 }}>{x.certificateAuthority.data.slice(0, 96)}...</code> : "-"]]} />
    </SpaceBetween>
  );
}

/* ── Compute: node groups + Fargate ────────────────────────────────────────── */
function Compute({ x }) {
  const notify = useNotify();
  const ng = useAsync(() => api.listNodegroups(x.name), [x.name]);
  const fp = useAsync(() => api.listFargateProfiles(x.name), [x.name]);
  usePoll(() => { ng.reload(); fp.reload(); }, [...(ng.data || []), ...(fp.data || [])].some((r) => BUSY.test(r.status)), 2500);
  const [sel, setSel] = useState([]);
  const [fsel, setFsel] = useState([]);
  const [create, setCreate] = useState(false);
  const [fcreate, setFcreate] = useState(false);
  const [del, setDel] = useState(false);
  const [scale, setScale] = useState(false);
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="eks.nodegroups" title="Node groups" description="Each node is a real k3s agent labelled eks.amazonaws.com/nodegroup.">
        <ResourceTable resourceName="Node groups" variant="embedded" items={ng.data || []} loading={ng.loading && !ng.data} error={ng.error} onRefresh={ng.reload} trackBy="nodegroupName"
          selectionType="single" selectedItems={sel} onSelectionChange={setSel} empty={{ title: "No node groups" }}
          columns={[
            { id: "n", header: "Group name", isRowHeader: true, cell: (g) => g.nodegroupName },
            { id: "s", header: "Status", cell: (g) => stat(g.status) },
            { id: "d", header: "Desired size", cell: (g) => g.scalingConfig.desiredSize },
            { id: "m", header: "Min / max", cell: (g) => `${g.scalingConfig.minSize} / ${g.scalingConfig.maxSize}` },
            { id: "i", header: "Instance types", cell: (g) => g.instanceTypes.join(", ") },
            { id: "a", header: "AMI type", cell: (g) => g.amiType },
            { id: "v", header: "Version", cell: (g) => g.version },
          ]}
          actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length || sel[0].status !== "ACTIVE"} onClick={() => setScale(true)}>Edit scaling</Button>
            <Button disabled={!sel.length || sel[0].status === "DELETING"} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" disabled={x.status !== "ACTIVE"} onClick={() => setCreate(true)}>Add node group</Button></SpaceBetween>} />
      </CapabilityContainer>
      <CapabilityContainer id="eks.fargate" title="Fargate profiles">
        <ResourceTable resourceName="Fargate profiles" variant="embedded" items={fp.data || []} loading={fp.loading && !fp.data} error={fp.error} onRefresh={fp.reload} trackBy="fargateProfileName"
          selectionType="single" selectedItems={fsel} onSelectionChange={setFsel} empty={{ title: "No Fargate profiles" }}
          columns={[
            { id: "n", header: "Profile name", isRowHeader: true, cell: (g) => g.fargateProfileName },
            { id: "s", header: "Status", cell: (g) => stat(g.status) },
            { id: "sel", header: "Selectors", cell: (g) => g.selectors.map((s) => s.namespace + (s.labels ? " " + JSON.stringify(s.labels) : "")).join("; ") },
            { id: "r", header: "Pod execution role", cell: (g) => g.podExecutionRoleArn.split("/").pop() },
          ]}
          actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!fsel.length} onClick={async () => { try { await api.deleteFargateProfile(x.name, fsel[0].fargateProfileName); notify.success("Deleting Fargate profile."); setFsel([]); fp.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
            <Button variant="primary" disabled={x.status !== "ACTIVE"} onClick={() => setFcreate(true)}>Add Fargate profile</Button></SpaceBetween>} />
      </CapabilityContainer>
      <NodegroupModal visible={create} x={x} onDismiss={() => setCreate(false)} onDone={() => { notify.success("Node group is being created."); ng.reload(); }} />
      <FargateModal visible={fcreate} x={x} onDismiss={() => setFcreate(false)} onDone={() => { notify.success("Fargate profile is being created."); fp.reload(); }} />
      <ScaleModal visible={scale} x={x} g={sel[0]} onDismiss={() => setScale(false)} onDone={() => { notify.success("Node group update started."); ng.reload(); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="node group" names={sel.map((g) => g.nodegroupName)}
        onConfirm={async () => { await api.deleteNodegroup(x.name, sel[0].nodegroupName); notify.success("Deleting node group."); setSel([]); ng.reload(); }} />
    </SpaceBetween>
  );
}

function RolePicker({ value, onChange, label = "Node IAM role" }) {
  const roles = useAsync(() => api.listRoles(), []);
  const mk = async () => {
    const arn = await api.ensureRole("eksNodeRole", label.startsWith("Pod") ? "eks-fargate-pods.amazonaws.com" : "ec2.amazonaws.com");
    roles.reload(); onChange({ label: "eksNodeRole", value: arn });
  };
  return (
    <FormField label={label} secondaryControl={<Button onClick={mk}>Create recommended role</Button>}>
      <Select selectedOption={value} onChange={({ detail }) => onChange(detail.selectedOption)} options={(roles.data || []).map((r) => ({ label: r.name, value: r.arn, description: r.arn }))} placeholder="Choose a role" ariaLabel={label} />
    </FormField>
  );
}

function NodegroupModal({ visible, x, onDismiss, onDone }) {
  const [f, setF] = useState({ name: "", role: null, type: "t3.medium", min: "1", max: "2", desired: "1" });
  const [err, setErr] = useState(null);
  const set = (k) => ({ detail }) => setF((o) => ({ ...o, [k]: detail.value }));
  return (
    <Modal visible={visible} onDismiss={onDismiss} size="large" header="Add node group"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!f.name || !f.role} onClick={async () => { setErr(null); try {
          await api.createNodegroup(x.name, { nodegroupName: f.name, nodeRole: f.role.value, subnets: x.resourcesVpcConfig.subnetIds, instanceTypes: [f.type],
            scalingConfig: { minSize: Number(f.min), maxSize: Number(f.max), desiredSize: Number(f.desired) } });
          onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Create</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="Name"><Input value={f.name} onChange={set("name")} ariaLabel="Node group name" /></FormField>
        <RolePicker value={f.role} onChange={(r) => setF((o) => ({ ...o, role: r }))} />
        <FormField label="Instance type" description="Recorded and used as the node.kubernetes.io/instance-type label."><Input value={f.type} onChange={set("type")} /></FormField>
        <ColumnLayout columns={3}>
          <FormField label="Desired size"><Input type="number" value={f.desired} onChange={set("desired")} ariaLabel="Desired size" /></FormField>
          <FormField label="Minimum size"><Input type="number" value={f.min} onChange={set("min")} /></FormField>
          <FormField label="Maximum size"><Input type="number" value={f.max} onChange={set("max")} /></FormField>
        </ColumnLayout>
      </SpaceBetween>
    </Modal>
  );
}

function ScaleModal({ visible, x, g, onDismiss, onDone }) {
  const [f, setF] = useState(null);
  const [err, setErr] = useState(null);
  const cur = f || (g && { min: String(g.scalingConfig.minSize), max: String(g.scalingConfig.maxSize), desired: String(g.scalingConfig.desiredSize) });
  const set = (k) => ({ detail }) => setF({ ...cur, [k]: detail.value });
  if (!g) return null;
  return (
    <Modal visible={visible} onDismiss={() => { setF(null); onDismiss(); }} header={`Edit scaling: ${g.nodegroupName}`}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" onClick={async () => { setErr(null); try { await api.updateNodegroupConfig(x.name, g.nodegroupName, { scalingConfig: { minSize: Number(cur.min), maxSize: Number(cur.max), desiredSize: Number(cur.desired) } }); setF(null); onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Save changes</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="Desired size"><Input type="number" value={cur.desired} onChange={set("desired")} ariaLabel="Desired size" /></FormField>
        <FormField label="Minimum size"><Input type="number" value={cur.min} onChange={set("min")} /></FormField>
        <FormField label="Maximum size"><Input type="number" value={cur.max} onChange={set("max")} /></FormField></SpaceBetween>
    </Modal>
  );
}

function FargateModal({ visible, x, onDismiss, onDone }) {
  const [f, setF] = useState({ name: "", role: null, ns: "default" });
  const [err, setErr] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Add Fargate profile"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!f.name || !f.role} onClick={async () => { setErr(null); try { await api.createFargateProfile(x.name, { fargateProfileName: f.name, podExecutionRoleArn: f.role.value, selectors: [{ namespace: f.ns }] }); onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Create</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="Name"><Input value={f.name} onChange={({ detail }) => setF({ ...f, name: detail.value })} ariaLabel="Profile name" /></FormField>
        <RolePicker value={f.role} onChange={(r) => setF({ ...f, role: r })} label="Pod execution role" />
        <FormField label="Namespace selector"><Input value={f.ns} onChange={({ detail }) => setF({ ...f, ns: detail.value })} /></FormField></SpaceBetween>
    </Modal>
  );
}

/* ── Networking ────────────────────────────────────────────────────────────── */
function Networking({ x, reload }) {
  const notify = useNotify();
  const v = x.resourcesVpcConfig || {};
  const [ep, setEp] = useState(false);
  const [mode, setMode] = useState(v.endpointPublicAccess && v.endpointPrivateAccess ? "both" : v.endpointPrivateAccess ? "private" : "public");
  const [err, setErr] = useState(null);
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="eks.cluster.lifecycle" title="Networking">
        <ColumnLayout columns={3} variant="text-grid">
          {[["VPC", v.vpcId], ["Cluster security group", v.clusterSecurityGroupId], ["Subnets", (v.subnetIds || []).join(", ")], ["Additional security groups", (v.securityGroupIds || []).join(", ")],
            ["Service IPv4 range", x.kubernetesNetworkConfig?.serviceIpv4Cidr], ["IP family", x.kubernetesNetworkConfig?.ipFamily]].map(([l, val]) => (
            <div key={l}><Box variant="awsui-key-label">{l}</Box><div style={{ wordBreak: "break-all" }}>{val || "-"}</div></div>))}
        </ColumnLayout>
      </CapabilityContainer>
      <CapabilityContainer id="eks.cluster.updates" title="Cluster endpoint access" actions={<Button disabled={x.status !== "ACTIVE"} onClick={() => setEp(true)}>Manage endpoint access</Button>}>
        <ColumnLayout columns={3} variant="text-grid">
          {[["Public access", v.endpointPublicAccess ? "Enabled" : "Disabled"], ["Private access", v.endpointPrivateAccess ? "Enabled" : "Disabled"], ["Public access source allowlist", (v.publicAccessCidrs || []).join(", ")]].map(([l, val]) => (
            <div key={l}><Box variant="awsui-key-label">{l}</Box><div>{val || "-"}</div></div>))}
        </ColumnLayout>
      </CapabilityContainer>
      <Modal visible={ep} onDismiss={() => setEp(false)} header="Manage endpoint access"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setEp(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await api.updateClusterConfig(x.name, { resourcesVpcConfig: { endpointPublicAccess: mode !== "private", endpointPrivateAccess: mode !== "public" } }); notify.success("Endpoint access update started."); setEp(false); reload(); } catch (e) { setErr(e); } }}>Save changes</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)} items={[{ value: "public", label: "Public" }, { value: "both", label: "Public and private" }, { value: "private", label: "Private" }]} /></SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
}

/* ── Add-ons ───────────────────────────────────────────────────────────────── */
function Addons({ x }) {
  const notify = useNotify();
  const t = useAsync(() => api.listAddons(x.name), [x.name]);
  usePoll(t.reload, (t.data || []).some((a) => BUSY.test(a.status)), 2500);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  return (
    <>
      <CapabilityContainer id="eks.addons.managed" title="Add-ons" description="coredns and kube-proxy are provided by k3s; other managed add-ons are accepted and stored.">
        <ResourceTable resourceName="Add-ons" variant="embedded" items={t.data || []} loading={t.loading && !t.data} error={t.error} onRefresh={t.reload} trackBy="addonName"
          selectionType="single" selectedItems={sel} onSelectionChange={setSel} empty={{ title: "No add-ons" }}
          columns={[
            { id: "n", header: "Name", isRowHeader: true, cell: (a) => a.addonName },
            { id: "v", header: "Version", cell: (a) => a.addonVersion },
            { id: "s", header: "Status", cell: (a) => stat(a.status) },
            { id: "p", header: "Publisher", cell: (a) => a.publisher },
          ]}
          actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Remove</Button>
            <Button variant="primary" disabled={x.status !== "ACTIVE"} onClick={() => setCreate(true)}>Get more add-ons</Button></SpaceBetween>} />
      </CapabilityContainer>
      <AddonModal visible={create} x={x} onDismiss={() => setCreate(false)} onDone={() => { notify.success("Add-on is being installed."); t.reload(); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="add-on" names={sel.map((a) => a.addonName)}
        onConfirm={async () => { await api.deleteAddon(x.name, sel[0].addonName); notify.success("Removing add-on."); setSel([]); t.reload(); }} />
    </>
  );
}

function AddonModal({ visible, x, onDismiss, onDone }) {
  const cat = useAsync(() => api.describeAddonVersions(x.version), [x.version]);
  const [name, setName] = useState(null);
  const [ver, setVer] = useState(null);
  const [err, setErr] = useState(null);
  const versions = useMemo(() => (cat.data || []).find((a) => a.addonName === name?.value)?.addonVersions || [], [cat.data, name]);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Select add-on"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!name} onClick={async () => { setErr(null); try { await api.createAddon(x.name, { addonName: name.value, ...(ver ? { addonVersion: ver.value } : {}) }); onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Create</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="Add-on"><Select selectedOption={name} onChange={({ detail }) => { setName(detail.selectedOption); setVer(null); }} options={(cat.data || []).map((a) => ({ label: a.addonName, value: a.addonName, description: a.type }))} placeholder="Choose an add-on" ariaLabel="Add-on" /></FormField>
        <FormField label="Version"><Select selectedOption={ver} onChange={({ detail }) => setVer(detail.selectedOption)} options={versions.map((v) => ({ label: v.addonVersion, value: v.addonVersion }))} placeholder="Default" ariaLabel="Add-on version" /></FormField></SpaceBetween>
    </Modal>
  );
}

/* ── Access: access entries + OIDC ─────────────────────────────────────────── */
function Access({ x }) {
  const notify = useNotify();
  const entries = useAsync(() => api.listAccessEntries(x.name).catch((e) => { if (/authentication mode/.test(e.message)) return null; throw e; }), [x.name]);
  const idp = useAsync(() => api.listIdentityProviders(x.name), [x.name]);
  const policies = useAsync(() => api.listAccessPolicies(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [assoc, setAssoc] = useState(false);
  const [oidc, setOidc] = useState(false);
  const [del, setDel] = useState(false);
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="eks.access_entries" title="IAM access entries" description={`Authentication mode: ${x.accessConfig?.authenticationMode}`}>
        {entries.data === null ? <Alert type="info">This cluster uses the CONFIG_MAP authentication mode, so access entries are not available.</Alert> :
          <ResourceTable resourceName="Access entries" variant="embedded" items={entries.data || []} loading={entries.loading && !entries.data} error={entries.error} onRefresh={entries.reload} trackBy="principalArn"
            selectionType="single" selectedItems={sel} onSelectionChange={setSel} empty={{ title: "No access entries" }}
            columns={[
              { id: "p", header: "IAM principal ARN", isRowHeader: true, cell: (e) => e.principalArn },
              { id: "t", header: "Type", cell: (e) => e.type },
              { id: "u", header: "Username", cell: (e) => e.username || "-" },
              { id: "g", header: "Groups", cell: (e) => (e.kubernetesGroups || []).join(", ") || "-" },
              { id: "pol", header: "Access policies", cell: (e) => e.policies.map((p) => `${p.policyArn.split("/").pop()} (${p.accessScope.type === "cluster" ? "cluster" : p.accessScope.namespaces.join(",")})`).join("; ") || "-" },
            ]}
            actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setAssoc(true)}>Add access policy</Button>
              <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
              <Button variant="primary" onClick={() => setCreate(true)}>Create access entry</Button></SpaceBetween>} />}
      </CapabilityContainer>
      <CapabilityContainer id="eks.oidc_providers" title="OIDC identity providers">
        <ResourceTable resourceName="Identity providers" variant="embedded" items={idp.data || []} loading={idp.loading && !idp.data} error={idp.error} onRefresh={idp.reload} trackBy="identityProviderConfigName"
          empty={{ title: "No identity providers" }}
          columns={[
            { id: "n", header: "Name", isRowHeader: true, cell: (i) => i.identityProviderConfigName },
            { id: "u", header: "Issuer URL", cell: (i) => i.issuerUrl },
            { id: "c", header: "Client ID", cell: (i) => i.clientId },
            { id: "s", header: "Status", cell: (i) => stat(i.status) },
            { id: "a", header: "", cell: (i) => <Button variant="inline-link" onClick={async () => { try { await api.disassociateOidc(x.name, i.identityProviderConfigName); notify.success("Disassociating identity provider."); idp.reload(); } catch (e) { notify.error(e); } }}>Disassociate</Button> },
          ]}
          actions={<Button variant="primary" onClick={() => setOidc(true)}>Associate identity provider</Button>} />
      </CapabilityContainer>
      <AccessEntryModal visible={create} x={x} onDismiss={() => setCreate(false)} onDone={() => { notify.success("Access entry created."); entries.reload(); }} />
      <AssociateModal visible={assoc} x={x} entry={sel[0]} policies={policies.data || []} onDismiss={() => setAssoc(false)} onDone={() => { notify.success("Access policy associated."); entries.reload(); }} />
      <OidcModal visible={oidc} x={x} onDismiss={() => setOidc(false)} onDone={() => { notify.success("Identity provider is being associated."); idp.reload(); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="access entry" names={["delete"]} confirmText="delete"
        onConfirm={async () => { await api.deleteAccessEntry(x.name, sel[0].principalArn); notify.success("Access entry deleted."); setSel([]); entries.reload(); }} />
    </SpaceBetween>
  );
}

function AccessEntryModal({ visible, x, onDismiss, onDone }) {
  const [f, setF] = useState({ arn: "", groups: "" });
  const [err, setErr] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create access entry"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!f.arn} onClick={async () => { setErr(null); try { await api.createAccessEntry(x.name, { principalArn: f.arn, kubernetesGroups: f.groups.split(",").map((s) => s.trim()).filter(Boolean) }); onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Create</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="IAM principal ARN"><Input value={f.arn} onChange={({ detail }) => setF({ ...f, arn: detail.value })} placeholder="arn:aws:iam::123456789012:role/developers" ariaLabel="IAM principal ARN" /></FormField>
        <FormField label="Kubernetes groups (optional)" description="Comma separated; names starting with system: are reserved."><Input value={f.groups} onChange={({ detail }) => setF({ ...f, groups: detail.value })} /></FormField></SpaceBetween>
    </Modal>
  );
}

function AssociateModal({ visible, x, entry, policies, onDismiss, onDone }) {
  const [p, setP] = useState(null);
  const [scope, setScope] = useState("cluster");
  const [ns, setNs] = useState("");
  const [err, setErr] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Add access policy"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!p} onClick={async () => { setErr(null); try { await api.associateAccessPolicy(x.name, entry.principalArn, { policyArn: p.value, accessScope: scope === "cluster" ? { type: "cluster" } : { type: "namespace", namespaces: ns.split(",").map((s) => s.trim()).filter(Boolean) } }); onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Add policy</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="Policy name"><Select selectedOption={p} onChange={({ detail }) => setP(detail.selectedOption)} options={policies.map((q) => ({ label: q.name, value: q.arn }))} placeholder="Choose a policy" ariaLabel="Policy name" /></FormField>
        <FormField label="Access scope"><RadioGroup value={scope} onChange={({ detail }) => setScope(detail.value)} items={[{ value: "cluster", label: "Cluster" }, { value: "namespace", label: "Kubernetes namespace" }]} /></FormField>
        {scope === "namespace" && <FormField label="Namespaces" description="Comma separated"><Input value={ns} onChange={({ detail }) => setNs(detail.value)} ariaLabel="Namespaces" /></FormField>}
      </SpaceBetween>
    </Modal>
  );
}

function OidcModal({ visible, x, onDismiss, onDone }) {
  const [f, setF] = useState({ name: "", issuer: "https://", client: "", claim: "email" });
  const [err, setErr] = useState(null);
  const set = (k) => ({ detail }) => setF((o) => ({ ...o, [k]: detail.value }));
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Associate OIDC identity provider"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!f.name || !f.client} onClick={async () => { setErr(null); try { await api.associateOidc(x.name, { identityProviderConfigName: f.name, issuerUrl: f.issuer, clientId: f.client, usernameClaim: f.claim }); onDismiss(); onDone(); } catch (e) { setErr(e); } }}>Associate</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m"><ErrorAlert error={err} />
        <FormField label="Name"><Input value={f.name} onChange={set("name")} ariaLabel="Name" /></FormField>
        <FormField label="Issuer URL"><Input value={f.issuer} onChange={set("issuer")} ariaLabel="Issuer URL" /></FormField>
        <FormField label="Client ID"><Input value={f.client} onChange={set("client")} ariaLabel="Client ID" /></FormField>
        <FormField label="Username claim"><Input value={f.claim} onChange={set("claim")} /></FormField></SpaceBetween>
    </Modal>
  );
}

/* ── Observability: control plane logging (stored setting) ─────────────────── */
function Observability({ x, reload }) {
  const notify = useNotify();
  const on = new Set((x.logging?.clusterLogging || []).filter((e) => e.enabled).flatMap((e) => e.types));
  const [pick, setPick] = useState(null);
  const cur = pick || on;
  const [err, setErr] = useState(null);
  const dirty = LOG_TYPES.some((t) => cur.has(t) !== on.has(t));
  return (
    <CapabilityContainer id="eks.logging" title="Control plane logging" description="Choose the log types the control plane would send to CloudWatch Logs."
      actions={<Button variant="primary" disabled={!dirty || x.status !== "ACTIVE"} onClick={async () => { setErr(null); try {
        await api.updateClusterConfig(x.name, { logging: { clusterLogging: [{ types: LOG_TYPES.filter((t) => cur.has(t)), enabled: true }, { types: LOG_TYPES.filter((t) => !cur.has(t)), enabled: false }].filter((e) => e.types.length) } });
        notify.success("Logging update started."); setPick(null); reload(); } catch (e) { setErr(e); } }}>Save changes</Button>}>
      <SpaceBetween size="xs"><ErrorAlert error={err} />
        {LOG_TYPES.map((t) => <Checkbox key={t} checked={cur.has(t)} onChange={({ detail }) => setPick(new Set(detail.checked ? [...cur, t] : [...cur].filter((z) => z !== t)))}>{t}</Checkbox>)}</SpaceBetween>
    </CapabilityContainer>
  );
}

/* ── Update history ────────────────────────────────────────────────────────── */
function Updates({ x }) {
  const t = useAsync(() => api.listUpdates(x.name), [x.name, x.version, x.status]);
  usePoll(t.reload, (t.data || []).some((u) => u.status === "InProgress"), 2500);
  return (
    <CapabilityContainer id="eks.cluster.updates" title="Update history">
      <ResourceTable resourceName="Updates" variant="embedded" items={t.data || []} loading={t.loading && !t.data} error={t.error} onRefresh={t.reload} trackBy="id" empty={{ title: "No updates", subtitle: "Cluster version and configuration updates appear here." }}
        columns={[
          { id: "i", header: "Update ID", isRowHeader: true, cell: (u) => u.id },
          { id: "t", header: "Type", cell: (u) => u.type },
          { id: "s", header: "Status", cell: (u) => stat(u.status) },
          { id: "p", header: "Parameters", cell: (u) => u.params.map((p) => `${p.type}=${p.value}`).join(", ") },
          { id: "c", header: "Created", cell: (u) => fmtDate(u.createdAt) },
        ]} />
    </CapabilityContainer>
  );
}

/* ── Tags ──────────────────────────────────────────────────────────────────── */
function Tags({ arn }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTags(arn), [arn]);
  const [k, setK] = useState("");
  const [v, setV] = useState("");
  const items = Object.entries(t.data || {}).map(([key, value]) => ({ key, value }));
  return (
    <CapabilityContainer id="eks.cluster.tags" title="Tags">
      <SpaceBetween size="m">
        <ResourceTable resourceName="Tags" variant="embedded" items={items} loading={t.loading && !t.data} error={t.error} onRefresh={t.reload} trackBy="key" empty={{ title: "No tags" }}
          columns={[{ id: "k", header: "Key", isRowHeader: true, cell: (i) => i.key }, { id: "v", header: "Value", cell: (i) => i.value },
            { id: "r", header: "", cell: (i) => <Button variant="inline-link" onClick={async () => { await api.untagResource(arn, [i.key]); t.reload(); }}>Remove</Button> }]} />
        <ColumnLayout columns={3}>
          <FormField label="Key"><Input value={k} onChange={({ detail }) => setK(detail.value)} ariaLabel="Tag key" /></FormField>
          <FormField label="Value"><Input value={v} onChange={({ detail }) => setV(detail.value)} ariaLabel="Tag value" /></FormField>
          <FormField label=" "><Button disabled={!k} onClick={async () => { try { await api.tagResource(arn, { [k]: v }); notify.success("Tag added."); setK(""); setV(""); t.reload(); } catch (e) { notify.error(e); } }}>Add tag</Button></FormField>
        </ColumnLayout>
      </SpaceBetween>
    </CapabilityContainer>
  );
}
