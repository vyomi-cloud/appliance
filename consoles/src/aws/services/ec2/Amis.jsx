import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Link from "@cloudscape-design/components/link";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

export function Amis() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const t = useAsync(() => api.describeImages({ Owner: ["self"] }), []);
  return (
    <ContentLayout header={<Header variant="h1">Select an AMI</Header>}>
      <ResourceTable
        resourceName="Amazon Machine Images (AMIs)"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="imageId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter AMI by attribute or tag"
        empty={{ title: "No AMIs in this Region for: Owned by me." }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (x) => x.Tags?.Name || "-" },
          { id: "n2", header: "AMI name", cell: (x) => x.name },
          { id: "id", header: "AMI ID", cell: (x) => <Link href={href("ec2", "amis", x.imageId)} onFollow={follow}>{x.imageId}</Link> },
          { id: "src", header: "Source", cell: (x) => x.source === "quickstart" ? "-" : x.source },
          { id: "owner", header: "Owner", cell: (x) => x.imageOwnerId },
          { id: "vis", header: "Visibility", cell: (x) => (x.isPublic === "true" ? "Public" : "Private") },
          { id: "status", header: "Status", cell: (x) => x.imageState },
          { id: "created", header: "Creation date", cell: (x) => x.creationDate },
          { id: "plat", header: "Platform", cell: (x) => x.platformDetails },
          { id: "root", header: "Root device type", cell: (x) => x.rootDeviceType },
          { id: "bd", header: "Block devices", cell: (x) => x.BlockDeviceMapping.map((b) => b.deviceName).join(", ") },
          { id: "virt", header: "Virtualization", cell: (x) => x.virtualizationType },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate("ec2", "recycle-bin")}>Recycle Bin</Button>
            <Button onClick={() => navigate("ec2", "image-builder")}>EC2 Image Builder</Button>
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "perm", text: "Edit AMI permissions" }, { id: "copy", text: "Copy AMI" },
              { id: "dereg", text: "Deregister AMI", disabled: sel.length !== 1 },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "dereg") { await api.deregisterImage(sel[0].imageId); notify.success("AMI deregistered."); setSel([]); t.reload(); }
              else if (detail.id === "copy") { const id = await api.copyImage(sel[0].imageId, `${sel[0].name} - copy`); notify.success(`Copied to ${id}.`); t.reload(); }
              else navigate("ec2", "amis", sel[0].imageId);
            }}>Actions</ButtonDropdown>
            <Button variant="primary" disabled={sel.length !== 1} href={sel.length === 1 ? href("ec2", "launch-instance") + `?ami=${sel[0].imageId}` : undefined} onFollow={follow}>Launch instance from AMI</Button>
          </SpaceBetween>
        }
      />
    </ContentLayout>
  );
}

export function AmiDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeImage(params.id), [params.id]);
  const [permModal, setPermModal] = useState(false);
  const [acct, setAcct] = useState("");
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "AMI not found" }} />;
  const x = t.data;
  return (
    <ContentLayout header={
      <Header variant="h1" actions={<SpaceBetween direction="horizontal" size="xs">
        <Button href={href("ec2", "launch-instance") + `?ami=${x.imageId}`} onFollow={follow}>Launch instance from AMI</Button>
        <ButtonDropdown items={[{ id: "dereg", text: "Deregister AMI" }]} onItemClick={async () => { await api.deregisterImage(x.imageId); notify.success("AMI deregistered."); navigate("ec2", "amis"); }}>Actions</ButtonDropdown>
      </SpaceBetween>}>{`Image summary for ${x.imageId}`}</Header>
    }>
      <SpaceBetween size="l">
        <KeyValue title="Image summary" columns={4} items={[
          ["AMI ID", x.imageId], ["Image type", x.imageType], ["Platform details", x.platformDetails], ["Root device type", x.rootDeviceType],
          ["AMI name", x.name], ["Owner account ID", x.imageOwnerId], ["Architecture", x.architecture], ["Usage operation", "RunInstances"],
          ["Root device name", "/dev/xvda"], ["Status", x.imageState], ["Source", x.source], ["Virtualization type", x.virtualizationType],
          ["Boot mode", "-"], ["State reason", "-"], ["Creation date", x.creationDate], ["Kernel ID", "-"],
          ["Description", x.description || "-"], ["Block devices", x.BlockDeviceMapping.map((b) => b.deviceName).join(", ")],
        ]} />
        <Tabs tabs={[
          { id: "perm", label: "Permissions", content: (
            <Table variant="container" items={x.LaunchPermissions.map((a) => ({ id: a }))}
              header={<Header variant="h2" counter={`(${x.LaunchPermissions.length})`} actions={<Button onClick={() => setPermModal(true)}>Edit AMI permissions</Button>}>Shared accounts</Header>}
              columnDefinitions={[{ id: "a", header: "AWS account ID", cell: (r) => r.id }]}
              empty={<Box textAlign="center" color="inherit">No shared accounts</Box>} />
          ) },
          { id: "storage", label: "Storage", content: (
            <Table variant="container" items={x.BlockDeviceMapping} header={<Header variant="h2" counter={`(${x.BlockDeviceMapping.length})`}>Block devices</Header>}
              columnDefinitions={[{ id: "dev", header: "Device name", cell: (b) => b.deviceName }, { id: "snap", header: "Snapshot ID", cell: (b) => b.ebs?.snapshotId },
                { id: "size", header: "Size", cell: (b) => `${b.ebs?.volumeSize} GiB` }, { id: "type", header: "Volume type", cell: (b) => b.ebs?.volumeType },
                { id: "dot", header: "Delete on termination", cell: (b) => b.ebs?.deleteOnTermination }]} />
          ) },
          { id: "tags", label: "Tags", content: (
            <Table variant="container" items={Object.entries(x.Tags || {}).map(([k, v]) => ({ k, v }))} header={<Header variant="h2" counter={`(${Object.keys(x.Tags || {}).length})`} actions={<Button onClick={() => setPermModal("tags")}>Manage tags</Button>}>Tags</Header>}
              columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.k }, { id: "v", header: "Value", cell: (r) => r.v }]}
              empty={<Box textAlign="center" color="inherit">No tags</Box>} />
          ) },
        ]} />
      </SpaceBetween>
      <Modal visible={permModal === true} onDismiss={() => setPermModal(false)} header="Edit AMI permissions"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setPermModal(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { await api.addLaunchPermission(x.imageId, acct); notify.success(`Shared with account ${acct}.`); setPermModal(false); t.reload(); }}>Save</Button></SpaceBetween></Box>}>
        <FormField label="AWS account ID"><Input value={acct} onChange={({ detail }) => setAcct(detail.value)} placeholder="123456789012" ariaLabel="AWS account ID" /></FormField>
      </Modal>
      <Modal visible={permModal === "tags"} onDismiss={() => setPermModal(false)} header="Manage tags" size="large"
        footer={<Box float="right"><Button variant="primary" onClick={() => setPermModal(false)}>Close</Button></Box>}>
        <TagManager resourceId={x.imageId} tags={x.Tags} onDone={() => { setPermModal(false); t.reload(); }} />
      </Modal>
    </ContentLayout>
  );
}

function TagManager({ resourceId, tags, onDone }) {
  const notify = useNotify();
  const [edited, setEdited] = useState(Object.entries(tags || {}).map(([Key, Value]) => ({ key: Key, value: Value, existing: true })));
  const save = async () => {
    const kept = edited.filter((t) => !t.markedForRemoval && t.key);
    const removed = edited.filter((t) => t.markedForRemoval && t.existing).map((t) => t.key);
    if (kept.length) await api.createTags([resourceId], Object.fromEntries(kept.map((t) => [t.key, t.value || ""])));
    if (removed.length) await api.deleteTags([resourceId], removed);
    notify.success("Tags updated."); onDone();
  };
  return <SpaceBetween size="l"><TagEditor tags={edited} onChange={({ detail }) => setEdited(detail.tags)} i18nStrings={TAG_I18N} /><Button variant="primary" onClick={save}>Save</Button></SpaceBetween>;
}
