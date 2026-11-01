import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Table from "@cloudscape-design/components/table";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import * as api from "./api.js";

const NODE_TYPES = ["dax.t3.small", "dax.t3.medium", "dax.r4.large", "dax.r4.xlarge", "dax.r4.2xlarge", "dax.r5.large"];
const NODE_TYPE_SPECS = [
  { type: "dax.t3.small", vcpu: 2, memory: "1.5", network: "Low to Moderate" },
  { type: "dax.t3.medium", vcpu: 2, memory: "4", network: "Low to Moderate" },
  { type: "dax.r4.large", vcpu: 2, memory: "15.25", network: "Up to 10 Gigabit" },
  { type: "dax.r4.xlarge", vcpu: 4, memory: "30.5", network: "Up to 10 Gigabit" },
  { type: "dax.r4.2xlarge", vcpu: 8, memory: "61", network: "Up to 10 Gigabit" },
  { type: "dax.r5.large", vcpu: 2, memory: "16", network: "Up to 10 Gigabit" },
];

function CreateClusterModal({ visible, onDismiss, onCreated, subnetGroups, parameterGroups }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [nodeType, setNodeType] = useState(NODE_TYPES[0]);
  const [rf, setRf] = useState("3");
  const [iamRoleArn, setIamRoleArn] = useState("");
  const [subnetGroup, setSubnetGroup] = useState("");
  const [parameterGroup, setParameterGroup] = useState("default.dax1.0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createDaxCluster({
        ClusterName: name, Description: description, NodeType: nodeType, ReplicationFactor: Number(rf) || 1,
        IamRoleArn: iamRoleArn, ...(subnetGroup ? { SubnetGroupName: subnetGroup } : {}),
        ParameterGroupName: parameterGroup,
      });
      notify.success(`Creating DAX cluster "${name}".`);
      onCreated(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} size="medium" onDismiss={onDismiss} header="Create DAX cluster"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !iamRoleArn} onClick={submit}>Create cluster</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Header variant="h3">Cluster details</Header>
        <FormField label="Cluster name">
          <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Cluster name" />
        </FormField>
        <FormField label="Description - optional">
          <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
        </FormField>
        <FormField label="Node type">
          <Select selectedOption={{ value: nodeType, label: nodeType }} onChange={({ detail }) => setNodeType(detail.selectedOption.value)}
            options={NODE_TYPES.map((t) => ({ value: t, label: t }))} ariaLabel="Node type" />
        </FormField>
        <Table variant="embedded" items={NODE_TYPE_SPECS} header={<Header variant="h3">Node types</Header>}
          columnDefinitions={[
            { id: "type", header: "Node type", cell: (n) => n.type },
            { id: "vcpu", header: "vCPU", cell: (n) => n.vcpu },
            { id: "mem", header: "Memory (GiB)", cell: (n) => n.memory },
            { id: "net", header: "Network performance", cell: (n) => n.network },
          ]} />
        <FormField label="Number of nodes">
          <Input type="number" value={rf} onChange={({ detail }) => setRf(detail.value)} ariaLabel="Number of nodes" />
        </FormField>
        <FormField label="IAM role ARN" description="The role DAX uses to access your DynamoDB tables.">
          <Input value={iamRoleArn} onChange={({ detail }) => setIamRoleArn(detail.value)}
            placeholder="arn:aws:iam::123456789012:role/dax-access" ariaLabel="IAM role ARN" />
        </FormField>
        <FormField label="Subnet group - optional">
          <Select selectedOption={subnetGroup ? { value: subnetGroup, label: subnetGroup } : null}
            placeholder="Choose a subnet group" onChange={({ detail }) => setSubnetGroup(detail.selectedOption.value)}
            options={subnetGroups.map((s) => ({ value: s.SubnetGroupName, label: s.SubnetGroupName }))} ariaLabel="Subnet group" />
        </FormField>
        <FormField label="Parameter group">
          <Select selectedOption={{ value: parameterGroup, label: parameterGroup }}
            onChange={({ detail }) => setParameterGroup(detail.selectedOption.value)}
            options={parameterGroups.map((p) => ({ value: p.ParameterGroupName, label: p.ParameterGroupName }))} ariaLabel="Parameter group" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function ClusterDetailsModal({ cluster, onDismiss, onChanged }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (!cluster) return null;
  const nodes = cluster.Nodes || [];

  const reboot = async (nodeId) => {
    setBusy(true); setError(null);
    try { await api.rebootDaxNode(cluster.ClusterName, nodeId); notify.success(`Rebooting node ${nodeId}.`); onChanged(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  const increase = async () => {
    setBusy(true); setError(null);
    try {
      await api.increaseDaxReplicationFactor(cluster.ClusterName, nodes.length + 1);
      notify.success("Increasing replication factor."); onChanged();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const decrease = async () => {
    setBusy(true); setError(null);
    try {
      await api.decreaseDaxReplicationFactor(cluster.ClusterName, Math.max(1, nodes.length - 1));
      notify.success("Decreasing replication factor."); onChanged();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={!!cluster} onDismiss={onDismiss} size="large" header={cluster.ClusterName}
      footer={<Box float="right"><Button onClick={onDismiss}>Close</Button></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <KeyValue columns={2} items={[
          ["Status", cluster.Status], ["Node type", cluster.NodeType],
          ["Cluster ARN", cluster.ClusterArn], ["Endpoint", `${cluster.ClusterDiscoveryEndpoint?.Address}:${cluster.ClusterDiscoveryEndpoint?.Port}`],
          ["Parameter group", cluster.ParameterGroup?.ParameterGroupName], ["Subnet group", cluster.SubnetGroup || "-"],
          ["IAM role ARN", cluster.IamRoleArn], ["Encryption", cluster.SSEDescription?.Status],
        ]} />
        <Table variant="embedded" items={nodes}
          header={<Header variant="h3" counter={`(${nodes.length})`} actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button disabled={busy || nodes.length <= 1} onClick={decrease}>Decrease replication factor</Button>
              <Button disabled={busy} onClick={increase}>Increase replication factor</Button>
            </SpaceBetween>
          }>Nodes</Header>}
          columnDefinitions={[
            { id: "id", header: "Node ID", cell: (n) => n.NodeId },
            { id: "status", header: "Status", cell: (n) => <StatusIndicator type={n.NodeStatus === "available" ? "success" : "in-progress"}>{n.NodeStatus}</StatusIndicator> },
            { id: "az", header: "Availability Zone", cell: (n) => n.AvailabilityZone },
            { id: "ep", header: "Endpoint", cell: (n) => `${n.Endpoint?.Address}:${n.Endpoint?.Port}` },
            { id: "reboot", header: "", cell: (n) => <Button disabled={busy} onClick={() => reboot(n.NodeId)}>Reboot</Button> },
          ]} />
      </SpaceBetween>
    </Modal>
  );
}

export default function DaxClusters() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [details, setDetails] = useState(null);
  const clusters = useAsync(() => api.describeDaxClusters(), []);
  const subnetGroups = useAsync(() => api.describeDaxSubnetGroups(), []);
  const parameterGroups = useAsync(() => api.describeDaxParameterGroups(), []);

  const reload = () => { clusters.reload(); if (details) api.describeDaxClusters([details.ClusterName]).then((cs) => setDetails(cs[0] || null)); };

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="dynamodb.dax.clusters" />}>Clusters</Header>}>
      <ResourceTable
        resourceName="Clusters"
        items={clusters.data || []}
        loading={clusters.loading}
        error={clusters.error}
        onRefresh={clusters.reload}
        trackBy="ClusterName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={[
          { id: "name", header: "Cluster name", isRowHeader: true, cell: (c) => c.ClusterName },
          { id: "status", header: "Status", cell: (c) => <StatusIndicator type={c.Status === "available" ? "success" : "in-progress"}>{c.Status}</StatusIndicator> },
          { id: "type", header: "Node type", cell: (c) => c.NodeType },
          { id: "nodes", header: "Nodes", cell: (c) => c.TotalNodes },
          { id: "az", header: "Availability Zones", cell: (c) => [...new Set((c.Nodes || []).map((n) => n.AvailabilityZone))].join(", ") },
          { id: "endpoint", header: "Endpoint", cell: (c) => c.ClusterDiscoveryEndpoint?.Address },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setDetails(sel[0])}>View details</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create cluster</Button>
          </SpaceBetween>
        }
        empty={{ title: "No clusters", subtitle: "You have not created any DAX clusters yet.", action: <Button onClick={() => setCreate(true)}>Create cluster</Button> }}
      />
      <CreateClusterModal visible={create} onDismiss={() => setCreate(false)} onCreated={clusters.reload}
        subnetGroups={subnetGroups.data || []} parameterGroups={parameterGroups.data || []} />
      <ClusterDetailsModal cluster={details} onDismiss={() => setDetails(null)} onChanged={reload} />
      <DeleteModal visible={del} resourceType="cluster" names={sel.map((c) => c.ClusterName)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const c of sel) await api.deleteDaxCluster(c.ClusterName); notify.success(`${sel.length} cluster(s) deleted.`); setSel([]); clusters.reload(); }} />
    </ContentLayout>
  );
}
