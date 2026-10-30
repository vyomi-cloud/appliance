import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });

export function Volumes() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [attachModal, setAttachModal] = useState(false);
  const [instanceId, setInstanceId] = useState("");
  const [device, setDevice] = useState("/dev/sdf");
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeVolumes(), []);
  const instances = useAsync(() => api.describeInstances(), []).data || [];
  const rows = t.data || [];

  return (
    <SpaceBetween size="l">
      <NotSimulatedContainer title="Fault tolerance for all volumes in this Region" feature="Data Lifecycle Manager / backup fault-tolerance rollup" />
      <ResourceTable
        resourceName="Volumes"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="volumeId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        empty={{ title: "You currently have no volumes in this region", action: <Button href={href("ec2", "create-volume")} onFollow={follow}>Create volume</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (v) => v.Tags?.Name || "-" },
          { id: "id", header: "Volume ID", cell: (v) => <Link href={href("ec2", "volumes", v.volumeId)} onFollow={follow}>{v.volumeId}</Link> },
          { id: "type", header: "Type", cell: (v) => v.volumeType },
          { id: "size", header: "Size", cell: (v) => `${v.size} GiB` },
          { id: "iops", header: "IOPS", cell: (v) => v.iops || "-" },
          { id: "tp", header: "Throughput", cell: (v) => v.throughput || "-" },
          { id: "owner", header: "Owner ID", cell: () => "123456789012" },
          { id: "snap", header: "Snapshot ID", cell: (v) => v.snapshotId || "-" },
          { id: "created", header: "Created", cell: (v) => v.createTime },
          { id: "az", header: "Availability Zone", cell: (v) => v.availabilityZone },
          { id: "state", header: "Volume state", cell: (v) => v.status },
          { id: "alarm", header: "Alarm status", cell: () => "-" },
          { id: "attached", header: "Attached resources", cell: (v) => v.Attachments.map((a) => a.instanceId).join(", ") || "-" },
          { id: "vs", header: "Volume status", cell: () => "ok" },
          { id: "enc", header: "Encryption", cell: (v) => (v.encrypted === "true" ? "Encrypted" : "Not encrypted") },
          { id: "kms", header: "KMS key ID", cell: (v) => v.kmsKeyId || "-" },
          { id: "ma", header: "Multi-Attach enabled", cell: (v) => v.multiAttachEnabled },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate("ec2", "recycle-bin")}>Recycle Bin</Button>
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "attach", text: "Attach volume", disabled: sel.length !== 1 || sel[0]?.status !== "available" },
              { id: "detach", text: "Detach volume", disabled: sel.some((v) => v.status !== "in-use") },
              { id: "snap", text: "Create snapshot", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete volume" },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "attach") setAttachModal(true);
              else if (detail.id === "detach") { await Promise.all(sel.map((v) => api.detachVolume(v.volumeId, v.Attachments[0]?.instanceId))); notify.success("Detaching volume(s)."); setSel([]); t.reload(); }
              else if (detail.id === "snap") navigate("ec2", "create-snapshot", sel[0].volumeId);
              else if (detail.id === "delete") setDel(true);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-volume")} onFollow={follow}>Create volume</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={attachModal} onDismiss={() => setAttachModal(false)} header="Attach volume"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setAttachModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!instanceId} onClick={async () => { await api.attachVolume(sel[0].volumeId, instanceId, device); notify.success("Attaching volume."); setAttachModal(false); setSel([]); t.reload(); }}>Attach volume</Button></SpaceBetween></Box>}>
        <SpaceBetween size="l">
          <FormField label="Instance"><Select selectedOption={instanceId ? opt(instanceId) : null} onChange={({ detail }) => setInstanceId(detail.selectedOption.value)}
            options={instances.map((i) => ({ value: i.instanceId, label: `${i.instanceId} (${i.instanceState?.name})` }))} placeholder="Select an instance" ariaLabel="Instance" /></FormField>
          <FormField label="Device name"><Input value={device} onChange={({ detail }) => setDevice(detail.value)} ariaLabel="Device name" /></FormField>
        </SpaceBetween>
      </Modal>
      <DeleteModal visible={del} resourceType="volume" names={sel.map((v) => v.volumeId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const v of sel) await api.deleteVolume(v.volumeId); notify.success(`${sel.length} volume(s) deleted.`); setSel([]); t.reload(); }} />
    </SpaceBetween>
  );
}

export function VolumeDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeVolume(params.id), [params.id]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Volume not found" }} />;
  const v = t.data;
  const save = async (edited) => {
    const kept = edited.filter((x) => !x.markedForRemoval && x.key);
    const removed = edited.filter((x) => x.markedForRemoval && x.existing).map((x) => x.key);
    if (kept.length) await api.createTags([v.volumeId], Object.fromEntries(kept.map((x) => [x.key, x.value || ""])));
    if (removed.length) await api.deleteTags([v.volumeId], removed);
    notify.success("Tags updated."); t.reload();
  };
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />}>{`Volume ID: ${v.volumeId}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={4} items={[
          ["Volume ID", v.volumeId], ["Size", `${v.size} GiB`], ["Type", v.volumeType], ["Volume status", v.status],
          ["AWS Compute Optimizer finding", "Opt in for recommendations"], ["Volume state", v.status], ["IOPS", v.iops || "-"],
          ["Throughput", v.throughput || "-"], ["Encryption", v.encrypted === "true" ? "Encrypted" : "Not encrypted"],
          ["KMS key ID", v.kmsKeyId || "-"], ["Snapshot", v.snapshotId || "-"], ["Availability Zone", v.availabilityZone],
          ["Created", v.createTime], ["Multi-Attach enabled", v.multiAttachEnabled], ["Attached resources", v.Attachments.map((a) => `${a.instanceId} (${a.device})`).join(", ") || "-"],
          ["Outposts ARN", "-"],
        ]} />
        <Tabs tabs={[
          { id: "status", label: "Status checks", content: <KeyValue title="Status checks" columns={2} items={[["Volume status", v.status === "available" || v.status === "in-use" ? "ok" : v.status], ["I/O status", "ok"]]} /> },
          { id: "mon", label: "Monitoring", content: <NotSimulatedContainer title="CloudWatch metrics" /> },
          { id: "tags", label: "Tags", content: <TagsPanel resourceId={v.volumeId} tags={v.Tags} onSave={save} /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}

function TagsPanel({ resourceId, tags, onSave }) {
  const [open, setOpen] = useState(false);
  const rows = Object.entries(tags || {}).map(([k, val]) => ({ key: k, value: val, existing: true }));
  return (
    <>
      <Table variant="container" items={rows} header={<Header variant="h2" counter={`(${rows.length})`} actions={<Button onClick={() => setOpen(true)}>Manage tags</Button>}>Tags</Header>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.key }, { id: "v", header: "Value", cell: (r) => r.value || "-" }]}
        empty={<Box textAlign="center" color="inherit">No tags</Box>} />
      <Modal visible={open} onDismiss={() => setOpen(false)} header="Manage tags" size="large" footer={<Box float="right"><Button variant="primary" onClick={() => setOpen(false)}>Close</Button></Box>}>
        <Editor rows={rows} onSave={async (edited) => { await onSave(edited); setOpen(false); }} />
      </Modal>
    </>
  );
}

function Editor({ rows, onSave }) {
  const [edited, setEdited] = useState(rows);
  return <SpaceBetween size="l"><TagEditor tags={edited} onChange={({ detail }) => setEdited(detail.tags)} i18nStrings={TAG_I18N} /><Button variant="primary" onClick={() => onSave(edited)}>Save</Button></SpaceBetween>;
}

export function CreateVolume({ query }) {
  const notify = useNotify();
  const snapshots = useAsync(() => api.describeSnapshots(), []).data || [];
  const [resourceType, setResourceType] = useState("Volume");
  const [type, setType] = useState("gp3");
  const [size, setSize] = useState("100");
  const [iops, setIops] = useState("3000");
  const [throughput, setThroughput] = useState("125");
  const [az, setAz] = useState("us-east-1a");
  const [snapshotId, setSnapshotId] = useState(query.snapshot || "");
  const [encrypt, setEncrypt] = useState(false);
  const [kmsKey, setKmsKey] = useState("alias/aws/ebs");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const v = await api.createVolume({
        Size: Number(size), VolumeType: type, Iops: ["gp3", "io1", "io2"].includes(type) ? Number(iops) : undefined,
        Throughput: type === "gp3" ? Number(throughput) : undefined, AvailabilityZone: az, SnapshotId: snapshotId || undefined,
        Encrypted: encrypt, KmsKeyId: encrypt ? kmsKey : undefined,
        TagSpecification: tags.length ? [{ ResourceType: "volume", Tag: tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ Key: t.key, Value: t.value })) }] : undefined,
      });
      notify.success(`Creating volume ${v.volumeId}.`);
      navigate("ec2", "volumes");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create volume</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "volumes")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={submit}>Create volume</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Volume settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Resource type">
                <Select selectedOption={opt(resourceType)} onChange={({ detail }) => setResourceType(detail.selectedOption.value)} options={["Volume", "Instance"].map(opt)} ariaLabel="Resource type" />
              </FormField>
              {resourceType === "Instance" && <NotSimulatedContainer title="Create volume from an instance" feature="Snapshotting an instance from this form" note="Use Create snapshot from the Snapshots page instead." />}
              <FormField label="Volume type">
                <Select selectedOption={opt(type)} onChange={({ detail }) => setType(detail.selectedOption.value)}
                  options={["General Purpose SSD (gp3)", "General Purpose SSD (gp2)", "Provisioned IOPS SSD (io1)", "Provisioned IOPS SSD (io2)", "Cold HDD (sc1)", "Throughput Optimized HDD (st1)", "Magnetic (standard)"]
                    .map((l, i) => ({ value: ["gp3", "gp2", "io1", "io2", "sc1", "st1", "standard"][i], label: l }))} ariaLabel="Volume type" />
              </FormField>
              <FormField label="Size (GiB)" constraintText="Min: 1 GiB, Max: 65536 GiB."><Input type="number" value={size} onChange={({ detail }) => setSize(detail.value)} ariaLabel="Size (GiB)" /></FormField>
              {["gp3", "io1", "io2"].includes(type) && <FormField label="IOPS" constraintText="Min: 3000 IOPS, Max: 80000 IOPS."><Input type="number" value={iops} onChange={({ detail }) => setIops(detail.value)} ariaLabel="IOPS" /></FormField>}
              {type === "gp3" && <FormField label="Throughput (MiB/s)" constraintText="Min: 125 MiB, Max: 2000 MiB."><Input type="number" value={throughput} onChange={({ detail }) => setThroughput(detail.value)} ariaLabel="Throughput (MiB/s)" /></FormField>}
              <FormField label="Availability Zone">
                <Select selectedOption={opt(az)} onChange={({ detail }) => setAz(detail.selectedOption.value)} options={["us-east-1a", "us-east-1b", "us-east-1c"].map(opt)} ariaLabel="Availability Zone" />
              </FormField>
              <FormField label="Snapshot ID - optional">
                <Select selectedOption={snapshotId ? opt(snapshotId) : { value: "", label: "Don't create volume from a snapshot" }} onChange={({ detail }) => setSnapshotId(detail.selectedOption.value)}
                  options={[{ value: "", label: "Don't create volume from a snapshot" }, ...snapshots.map((s) => opt(s.snapshotId))]} ariaLabel="Snapshot ID - optional" />
              </FormField>
              <FormField label="Encryption" description="Use Amazon EBS encryption as an encryption solution for your EBS resources">
                <Checkbox checked={encrypt} onChange={({ detail }) => setEncrypt(detail.checked)}>Encrypt this volume</Checkbox>
              </FormField>
              {encrypt && <FormField label="KMS key"><Select selectedOption={opt(kmsKey)} onChange={({ detail }) => setKmsKey(detail.selectedOption.value)} options={[opt("alias/aws/ebs")]} ariaLabel="KMS key" /></FormField>}
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}>
            <FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
          </Container>
          <Container header={<Header variant="h2">Snapshot summary</Header>}>
            <Box variant="p">{snapshotId ? `Creating from snapshot ${snapshotId}.` : "Not applicable when creating a blank volume."}</Box>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
