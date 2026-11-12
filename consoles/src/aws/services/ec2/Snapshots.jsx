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
import Link from "@cloudscape-design/components/link";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });

export function Snapshots() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeSnapshots(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Select a snapshot above.</Header>}>
      <ResourceTable
        resourceName="Snapshots"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="snapshotId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={{ title: "You currently have no snapshots in this Region." }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (s) => s.Tags?.Name || "-" },
          { id: "id", header: "Snapshot ID", cell: (s) => s.snapshotId },
          { id: "fullsize", header: "Full snapshot size", cell: (s) => `${s.volumeSize} GiB` },
          { id: "volsize", header: "Volume size", cell: (s) => `${s.volumeSize} GiB` },
          { id: "desc", header: "Description", cell: (s) => s.description || "-" },
          { id: "tier", header: "Storage tier", cell: () => "Standard" },
          { id: "status", header: "Snapshot status", cell: (s) => s.status },
          { id: "started", header: "Started", cell: (s) => s.startTime },
          { id: "progress", header: "Progress", cell: (s) => s.progress },
          { id: "enc", header: "Encryption", cell: (s) => (s.encrypted === "true" ? "Encrypted" : "Not encrypted") },
          { id: "kms", header: "KMS key ID", cell: (s) => s.kmsKeyId || "-" },
          { id: "owner", header: "Owner ID", cell: (s) => s.ownerId },
          { id: "source", header: "Source", cell: (s) => s.volumeId },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate("ec2", "recycle-bin")}>Recycle Bin</Button>
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "copy", text: "Copy snapshot", disabled: sel.length !== 1 }, { id: "delete", text: "Delete snapshot" },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "copy") { const id = await api.copySnapshot(sel[0].snapshotId, `Copy of ${sel[0].snapshotId}`); notify.success(`Copying to ${id}.`); t.reload(); }
              else setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-snapshot")} onFollow={follow}>Create snapshot</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="snapshot" names={sel.map((s) => s.snapshotId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const s of sel) await api.deleteSnapshot(s.snapshotId); notify.success(`${sel.length} snapshot(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function CreateSnapshot({ params }) {
  const notify = useNotify();
  const volumes = useAsync(() => api.describeVolumes(), []).data || [];
  const [resourceType, setResourceType] = useState("Volume");
  const [volumeId, setVolumeId] = useState(params.volumeId || "");
  const [desc, setDesc] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const vol = volumes.find((v) => v.volumeId === volumeId);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const s = await api.createSnapshot(volumeId, desc, Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value])));
      notify.success(`Snapshot ${s.snapshotId} created.`);
      navigate("ec2", "snapshots");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create snapshot</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "snapshots")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={resourceType !== "Volume" || !volumeId} onClick={submit}>Create snapshot</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Details</Header>}>
            <SpaceBetween size="l">
              <FormField label="Resource type">
                <RadioGroup value={resourceType} onChange={({ detail }) => setResourceType(detail.value)} items={["Volume", "Instance"].map((v) => ({ value: v, label: v }))} />
              </FormField>
              {resourceType === "Volume" ? (
                <FormField label="Volume ID">
                  <Select selectedOption={volumeId ? opt(volumeId) : null} onChange={({ detail }) => setVolumeId(detail.selectedOption.value)}
                    options={volumes.map((v) => ({ value: v.volumeId, label: `${v.volumeId} (${v.size} GiB)` }))} placeholder="Select a volume" ariaLabel="Volume ID" />
                </FormField>
              ) : (
                <NotSimulatedContainer title="Snapshot an instance" feature="Multi-volume snapshot sets from an instance" note="Create a snapshot of each of the instance's volumes individually instead." />
              )}
              <FormField label="Description" constraintText="Up to 255 characters"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} ariaLabel="Description" /></FormField>
              <FormField label="Encryption"><Input readOnly value={vol?.encrypted === "true" ? "Encrypted (inherited from volume)" : "Not encrypted (inherited from volume)"} ariaLabel="Encryption" /></FormField>
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
