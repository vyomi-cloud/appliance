/* Customer managed keys — the main KMS key list: create, enable/disable, schedule/cancel
 * deletion, add an alias. Every action is a real TrentService call. */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Box from "@cloudscape-design/components/box";
import Alert from "@cloudscape-design/components/alert";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const statusType = (s) => (s === "Enabled" ? "success" : s === "PendingDeletion" ? "warning" : "stopped");

function ScheduleDeletionModal({ keys, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [days, setDays] = useState("30");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      for (const k of keys) await api.scheduleKeyDeletion(k.KeyId, Number(days));
      notify.success(`Scheduled ${keys.length} key(s) for deletion in ${days} days.`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Schedule key deletion"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Schedule deletion</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="m">
        <Alert type="warning">Once deleted, data encrypted under these keys is unrecoverable. {keys.length} key(s) selected.</Alert>
        {error && <ErrorAlert error={error} />}
        <FormField label="Waiting period (in days)" constraintText="7 to 30 days">
          <Input type="number" value={days} onChange={({ detail }) => setDays(detail.value)} ariaLabel="Waiting period (in days)" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function AddAliasModal({ keyId, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createAlias(`alias/${name}`, keyId); notify.success(`Added alias "${name}".`); onDone(); onDismiss(); setName(""); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Add alias"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Add alias</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} />}
        <FormField label="Alias" constraintText="Letters, numbers, '/', '_', '-'; cannot begin with aws/">
          <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="Enter alias" ariaLabel="Alias" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function CustomerManagedKeys() {
  const notify = useNotify();
  const t = useAsync(() => api.listCustomerManagedKeys(), []);
  const [sel, setSel] = useState([]);
  const [scheduleModal, setScheduleModal] = useState(false);
  const [aliasModal, setAliasModal] = useState(false);

  const run = async (fn, label) => {
    try { for (const k of sel) await fn(k.KeyId); notify.success(label); setSel([]); t.reload(); }
    catch (e) { notify.error(e); }
  };

  return (
    <>
      <ResourceTable
        resourceName="Customer managed keys"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="KeyId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter keys by properties or tags"
        empty={{ title: "No resources to display" }}
        columns={[
          { id: "alias", header: "Aliases", isRowHeader: true, cell: (k) => <Link href={href("kms", "customer-managed-keys", k.KeyId)} onFollow={follow}>{k.aliases[0] || k.KeyId}</Link> },
          { id: "id", header: "Key ID", cell: (k) => k.KeyId },
          { id: "status", header: "Status", cell: (k) => <StatusIndicator type={statusType(k.KeyState)}>{k.KeyState}</StatusIndicator> },
          { id: "type", header: "Key type", cell: (k) => api.keyType(k) },
          { id: "spec", header: "Key spec", cell: (k) => k.KeySpec },
          { id: "usage", header: "Key usage", cell: (k) => k.KeyUsage },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown
              items={[
                { id: "enable", text: "Enable", disabled: sel.length !== 1 || sel[0]?.KeyState !== "Disabled" },
                { id: "disable", text: "Disable", disabled: sel.length !== 1 || sel[0]?.KeyState !== "Enabled" },
                { id: "schedule", text: "Schedule key deletion", disabled: !sel.length || sel.some((k) => k.KeyState === "PendingDeletion") },
                { id: "cancel", text: "Cancel key deletion", disabled: !sel.length || sel.some((k) => k.KeyState !== "PendingDeletion") },
                { id: "alias", text: "Add to alias", disabled: sel.length !== 1 },
              ]}
              onItemClick={({ detail }) => {
                if (detail.id === "enable") run((id) => api.enableKey(id), "Key(s) enabled.");
                else if (detail.id === "disable") run((id) => api.disableKey(id), "Key(s) disabled.");
                else if (detail.id === "schedule") setScheduleModal(true);
                else if (detail.id === "cancel") run((id) => api.cancelKeyDeletion(id), "Key deletion canceled.");
                else if (detail.id === "alias") setAliasModal(true);
              }}
            >Key actions</ButtonDropdown>
            <Button variant="primary" onClick={() => navigate("kms", "create-key")}>Create key</Button>
          </SpaceBetween>
        }
      />
      <ScheduleDeletionModal keys={sel} visible={scheduleModal} onDismiss={() => setScheduleModal(false)} onDone={() => { setSel([]); t.reload(); }} />
      <AddAliasModal keyId={sel[0]?.KeyId} visible={aliasModal} onDismiss={() => setAliasModal(false)} onDone={() => { setSel([]); t.reload(); }} />
    </>
  );
}
