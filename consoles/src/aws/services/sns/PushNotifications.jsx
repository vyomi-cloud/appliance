/* Mobile push notifications — platform application CRUD is real and stateful. Vyomi has no Apple/Google account, so
 * the push gateway stub (core/sns_core.py) delivers the platform-native payload to the endpoint's push inbox and,
 * when the endpoint has a VyomiPushWebhook attribute, POSTs it there (core/capabilities/aws/sns.json: sns.mobile.push-delivery). */
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
import Table from "@cloudscape-design/components/table";
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

  const inbox = useAsync(() => api.listPushInbox(), []);
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
      <Box margin={{ top: "l" }}>
        <Table variant="container" header={<Header variant="h2" counter={`(${(inbox.data || []).length})`} info={<CapabilityBadge id="sns.mobile.push-delivery" />}
          actions={<Button iconName="refresh" onClick={inbox.reload} ariaLabel="Refresh push inbox" />}
          description="Payloads the push gateway delivered to registered endpoints (the simulated device inbox). Set the endpoint attribute VyomiPushWebhook to also POST them to your own URL.">Push inbox</Header>}
          items={inbox.data || []} loading={inbox.loading} trackBy="id" empty={<Box textAlign="center">No push messages delivered yet. Publish to a platform endpoint ARN.</Box>}
          columnDefinitions={[
            { id: "at", header: "Time", cell: (m) => m.at },
            { id: "platform", header: "Platform", cell: (m) => m.platform },
            { id: "endpoint", header: "Endpoint", cell: (m) => m.endpoint.split("/").slice(-1)[0].slice(0, 8) },
            { id: "payload", header: "Payload", cell: (m) => <code>{m.payload}</code> },
            { id: "delivery", header: "Delivery", cell: (m) => <StatusIndicator type={m.delivery === "webhook-failed" ? "error" : "success"}>{m.delivery}{m.webhook ? ` (${m.webhook})` : ""}</StatusIndicator> },
          ]} />
      </Box>
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
