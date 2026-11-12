import { useEffect, useState } from "react";
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
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

function SubnetGroupModal({ group, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState(group?.SubnetGroupName || "");
  const [description, setDescription] = useState(group?.Description || "");
  const [vpcId, setVpcId] = useState(group?.VpcId || "");
  const [selectedSubnets, setSelectedSubnets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const isEdit = !!group;
  const vpcs = useAsync(() => (visible ? api.listVpcsForDax() : Promise.resolve([])), [visible]);
  const subnets = useAsync(() => (visible && vpcId ? api.listSubnetsForDax(vpcId) : Promise.resolve([])), [visible, vpcId]);

  useEffect(() => {
    if (!visible) { setName(group?.SubnetGroupName || ""); setDescription(group?.Description || ""); setVpcId(group?.VpcId || ""); setSelectedSubnets([]); }
  }, [visible, group]);
  useEffect(() => {
    if (isEdit && group && subnets.data?.length) {
      const ids = new Set((group.Subnets || []).map((s) => s.SubnetIdentifier));
      setSelectedSubnets(subnets.data.filter((s) => ids.has(s.SubnetId)));
    }
  }, [isEdit, group, subnets.data]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const ids = selectedSubnets.map((s) => s.SubnetId);
      if (isEdit) await api.updateDaxSubnetGroup({ SubnetGroupName: name, Description: description, SubnetIds: ids });
      else await api.createDaxSubnetGroup({ SubnetGroupName: name, Description: description, SubnetIds: ids, VpcId: vpcId });
      notify.success(`Subnet group "${name}" ${isEdit ? "updated" : "created"}.`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} size="large" onDismiss={onDismiss} header={isEdit ? "Edit subnet group" : "Create subnet group"}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !selectedSubnets.length} onClick={submit}>{isEdit ? "Save" : "Create subnet group"}</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Subnet group name">
          <Input value={name} disabled={isEdit} onChange={({ detail }) => setName(detail.value)} ariaLabel="Subnet group name" />
        </FormField>
        <FormField label="Subnet group description" description="optional">
          <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Subnet group description" />
        </FormField>
        <FormField label="VPC ID">
          <Select selectedOption={vpcId ? { value: vpcId, label: vpcId } : null} placeholder="Choose a VPC"
            onChange={({ detail }) => { setVpcId(detail.selectedOption.value); setSelectedSubnets([]); }}
            options={(vpcs.data || []).map((v) => ({ value: v.VpcId, label: `${v.VpcId} (${v.CidrBlock})` }))} ariaLabel="VPC ID" />
        </FormField>
        <Table variant="embedded" items={subnets.data || []} loading={subnets.loading}
          header={<Header variant="h3" counter={`(${(subnets.data || []).length})`}>Subnets</Header>}
          selectionType="multi" selectedItems={selectedSubnets} trackBy="SubnetId"
          onSelectionChange={({ detail }) => setSelectedSubnets(detail.selectedItems)}
          columnDefinitions={[
            { id: "id", header: "Subnet ID", cell: (s) => s.SubnetId },
            { id: "az", header: "Availability Zone", cell: (s) => s.AvailabilityZone },
            { id: "cidr4", header: "IPv4 CIDR", cell: (s) => s.CidrBlock },
            { id: "cidr6", header: "IPv6 CIDR", cell: (s) => s.Ipv6CidrBlock || "-" },
          ]}
          empty={<Box textAlign="center" color="inherit">{vpcId ? "No subnets in this VPC." : "Choose a VPC to list its subnets."}</Box>} />
      </SpaceBetween>
    </Modal>
  );
}

export default function DaxSubnetGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);
  const groups = useAsync(() => api.describeDaxSubnetGroups(), []);

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="dynamodb.dax.subnet-groups" />}>Subnet groups</Header>}>
      <ResourceTable
        resourceName="Subnet groups"
        items={groups.data || []}
        loading={groups.loading}
        error={groups.error}
        onRefresh={groups.reload}
        trackBy="SubnetGroupName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (g) => g.SubnetGroupName },
          { id: "desc", header: "Description", cell: (g) => g.Description || "-" },
          { id: "vpc", header: "VPC ID", cell: (g) => g.VpcId },
          { id: "subnets", header: "Active subnets", cell: (g) => (g.Subnets || []).length },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setEdit(true)}>Edit</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create subnet group</Button>
          </SpaceBetween>
        }
        empty={{ title: "No subnet groups", subtitle: "You have not created any DAX subnet groups yet.", action: <Button onClick={() => setCreate(true)}>Create subnet group</Button> }}
      />
      <SubnetGroupModal group={null} visible={create} onDismiss={() => setCreate(false)} onDone={groups.reload} />
      <SubnetGroupModal group={edit ? sel[0] : null} visible={edit} onDismiss={() => setEdit(false)} onDone={groups.reload} />
      <DeleteModal visible={del} resourceType="subnet group" names={sel.map((g) => g.SubnetGroupName)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const g of sel) await api.deleteDaxSubnetGroup(g.SubnetGroupName); notify.success(`${sel.length} subnet group(s) deleted.`); setSel([]); groups.reload(); }} />
    </ContentLayout>
  );
}
