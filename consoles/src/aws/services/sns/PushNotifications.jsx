/* Mobile push notifications — platform application CRUD is real and stateful; Vyomi has
 * no real APNS/FCM/ADM gateway to reach, so no push is ever actually delivered to a device
 * (core/capabilities/aws/sns.json: sns.mobile.platform-apps). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Box from "@cloudscape-design/components/box";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityBadge, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const PLATFORMS = ["ADM", "APNS", "APNS_SANDBOX", "GCM", "BAIDU", "MPNS", "WNS"];

export default function PushNotifications() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState({ label: "GCM", value: "GCM" });
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const { data = [], loading, error: loadError, reload } = useAsync(async () => (await api.listPlatformApplications())
    .map((a) => ({ ...a, name: api.appName(a.arn), platform: api.appPlatform(a.arn) })), []);

  return (
    <ContentLayout header={<Header variant="h1" counter={`(${data.length})`} info={<CapabilityBadge id="sns.mobile.platform-apps" />}>Mobile push notifications</Header>}>
      <ResourceTable
        resourceName="Platform applications"
        items={data}
        trackBy="arn"
        loading={loading}
        error={loadError}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (a) => a.name },
          { id: "platform", header: "Platform", cell: (a) => a.platform },
          { id: "arn", header: "ARN", cell: (a) => a.arn },
          { id: "status", header: "Status", cell: (a) => <StatusIndicator type={a.attributes.Enabled === "false" ? "stopped" : "success"}>{a.attributes.Enabled === "false" ? "Disabled" : "Enabled"}</StatusIndicator> },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => { setEnabled(sel[0].attributes.Enabled !== "false"); setEditOpen(true); }}>Edit</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => { setName(""); setPlatform({ label: "GCM", value: "GCM" }); setCreateOpen(true); }}>Create platform application</Button>
          </SpaceBetween>
        }
        empty={{ title: "No platform applications", action: <Button onClick={() => setCreateOpen(true)}>Create platform application</Button> }}
      />
      <DeleteModal visible={del} resourceType="platform application" names={sel.map((a) => a.name)} confirmText="delete me" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const a of sel) await api.deletePlatformApplication(a.arn); notify.success("Platform application deleted."); setSel([]); reload(); }} />
      <Modal visible={createOpen} onDismiss={() => setCreateOpen(false)} header="Create platform application"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
            setBusy(true); setError(null);
            try { await api.createPlatformApplication(name, platform.value, "vyomi-demo-credential"); notify.success(`Platform application "${name}" created.${saveNotice("sns.mobile.platform-apps")}`); setCreateOpen(false); reload(); }
            catch (e) { setError(e); } finally { setBusy(false); }
          }}>Create platform application</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Application name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Application name" /></FormField>
          <FormField label="Push notification platform">
            <Select selectedOption={platform} onChange={({ detail }) => setPlatform(detail.selectedOption)} options={PLATFORMS.map((p) => ({ label: p, value: p }))} />
          </FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={editOpen} onDismiss={() => setEditOpen(false)} header="Edit platform application"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            try { await api.setPlatformApplicationAttributes(sel[0].arn, { Enabled: enabled ? "true" : "false" }); notify.success("Platform application updated."); setEditOpen(false); reload(); }
            finally { setBusy(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <Select selectedOption={{ label: enabled ? "Enabled" : "Disabled", value: enabled }} onChange={({ detail }) => setEnabled(detail.selectedOption.value)}
          options={[{ label: "Enabled", value: true }, { label: "Disabled", value: false }]} />
      </Modal>
    </ContentLayout>
  );
}
