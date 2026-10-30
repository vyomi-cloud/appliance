import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });

export function PlacementGroups() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describePlacementGroups(), []);
  const rows = t.data || [];
  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="ec2.placement-groups" />}>Placement groups</Header>}>
      <ResourceTable
        resourceName="Placement groups"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="groupId"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter Placement Group by attribute or tag"
        empty={{ title: "You do not have any placement groups in this region." }}
        columns={[
          { id: "name", header: "Group name", isRowHeader: true, cell: (g) => g.groupName },
          { id: "id", header: "Group Id", cell: (g) => g.groupId },
          { id: "strategy", header: "Strategy", cell: (g) => g.strategy },
          { id: "state", header: "State", cell: (g) => g.state },
          { id: "part", header: "Partition", cell: (g) => g.partitionCount || "-" },
          { id: "arn", header: "Group ARN", cell: (g) => g.groupArn },
          { id: "parent", header: "Parent group ID", cell: () => "-" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete placement group" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-placement-group")} onFollow={follow}>Create placement group</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="placement group" names={sel.map((g) => g.groupName)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deletePlacementGroup(sel[0].groupName); notify.success("Placement group deleted."); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function CreatePlacementGroup() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [strategy, setStrategy] = useState("Cluster");
  const [spreadLevel, setSpreadLevel] = useState("Rack");
  const [partitions, setPartitions] = useState("2");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const g = await api.createPlacementGroup(name, strategy.toLowerCase(), strategy === "Partition" ? Number(partitions) : undefined,
        Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value])));
      notify.success(`Placement group "${g.groupName}" created.`);
      navigate("ec2", "placement-groups");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create placement group</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "placement-groups")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create group</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Placement group settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
              <FormField label="Placement strategy"><RadioGroup value={strategy} onChange={({ detail }) => setStrategy(detail.value)} items={["Cluster", "Spread", "Partition"].map((v) => ({ value: v, label: v }))} /></FormField>
              {strategy === "Spread" && <FormField label="Spread level"><Select selectedOption={opt(spreadLevel)} onChange={({ detail }) => setSpreadLevel(detail.selectedOption.value)} options={["Rack", "Host"].map(opt)} ariaLabel="Spread level" /></FormField>}
              {strategy === "Partition" && <FormField label="Number of partitions"><Select selectedOption={opt(partitions)} onChange={({ detail }) => setPartitions(detail.selectedOption.value)} options={["2", "3", "4", "5", "6", "7"].map(opt)} ariaLabel="Number of partitions" /></FormField>}
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}>
            <FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
