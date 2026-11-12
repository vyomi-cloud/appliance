import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });

export default function NetworkInterfaces() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [createModal, setCreateModal] = useState(false);
  const [attachModal, setAttachModal] = useState(false);
  const [del, setDel] = useState(false);
  const [desc, setDesc] = useState("");
  const [subnetId, setSubnetId] = useState("");
  const [instanceId, setInstanceId] = useState("");
  const t = useAsync(() => api.describeNetworkInterfaces(), []);
  const instances = useAsync(() => api.describeInstances(), []).data || [];
  const subnets = useAsync(() => api.describeSubnets(), []).data || [];
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Select a network interface</Header>}>
      <ResourceTable
        resourceName="Network interfaces"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="networkInterfaceId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={{ title: "No network interfaces", action: <Button onClick={() => setCreateModal(true)}>Create network interface</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (e) => e.Tags?.Name || "-" },
          { id: "id", header: "Network interface ID", cell: (e) => e.networkInterfaceId },
          { id: "subnet", header: "Subnet ID", cell: (e) => e.subnetId },
          { id: "vpc", header: "VPC ID", cell: (e) => e.vpcId },
          { id: "az", header: "Availability Zone", cell: (e) => e.availabilityZone },
          { id: "sg", header: "Security group names", cell: (e) => e.Groups.map((g) => g.groupId).join(", ") || "-" },
          { id: "desc", header: "Description", cell: (e) => e.description || "-" },
          { id: "type", header: "Interface Type", cell: () => "interface" },
          { id: "status", header: "Status", cell: (e) => e.status },
          { id: "pub", header: "Public IPv4 address", cell: (e) => e.association?.publicIp || "-" },
          { id: "priv", header: "Primary private IPv4 address", cell: (e) => e.privateIpAddress },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "attach", text: "Attach", disabled: sel.length !== 1 || sel[0]?.status !== "available" },
              { id: "detach", text: "Detach", disabled: sel.some((e) => e.status !== "in-use") },
              { id: "delete", text: "Delete" },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "attach") setAttachModal(true);
              else if (detail.id === "detach") { await Promise.all(sel.map((e) => api.detachNetworkInterface(e.attachment.id))); notify.success("Detaching."); setSel([]); t.reload(); }
              else setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreateModal(true)}>Create network interface</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={createModal} onDismiss={() => setCreateModal(false)} header="Create network interface"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setCreateModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!subnetId} onClick={async () => { await api.createNetworkInterface(subnetId, desc, []); notify.success("Network interface created."); setCreateModal(false); setDesc(""); t.reload(); }}>Create network interface</Button></SpaceBetween></Box>}>
        <SpaceBetween size="l">
          <FormField label="Subnet"><Select selectedOption={subnetId ? opt(subnetId) : null} onChange={({ detail }) => setSubnetId(detail.selectedOption.value)}
            options={subnets.map((s) => ({ value: s.subnetId, label: `${s.subnetId} (${s.availabilityZone})` }))} placeholder="Select a subnet" ariaLabel="Subnet" /></FormField>
          <FormField label="Description"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} ariaLabel="Description" /></FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={attachModal} onDismiss={() => setAttachModal(false)} header="Attach network interface"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setAttachModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!instanceId} onClick={async () => { await api.attachNetworkInterface(sel[0].networkInterfaceId, instanceId, 1); notify.success("Attached."); setAttachModal(false); setSel([]); t.reload(); }}>Attach</Button></SpaceBetween></Box>}>
        <FormField label="Instance"><Select selectedOption={instanceId ? opt(instanceId) : null} onChange={({ detail }) => setInstanceId(detail.selectedOption.value)}
          options={instances.map((i) => opt(i.instanceId))} placeholder="Select an instance" ariaLabel="Instance" /></FormField>
      </Modal>
      <DeleteModal visible={del} resourceType="network interface" names={sel.map((e) => e.networkInterfaceId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const e of sel) await api.deleteNetworkInterface(e.networkInterfaceId); notify.success(`${sel.length} network interface(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}
