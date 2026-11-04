/* Shared modify/delete/snapshot actions — used by both the Databases list and the
 * database detail page header, so the two stay behaviorally identical. */
import { useEffect, useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Checkbox from "@cloudscape-design/components/checkbox";
import Select from "@cloudscape-design/components/select";
import { ErrorAlert } from "../../kit/common.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { INSTANCE_CLASSES } from "./engines.js";
import * as api from "./api.js";

export function ModifyModal({ db, visible, onDismiss, onDone, notify }) {
  const [cls, setCls] = useState(db?.DBInstanceClass || "db.t3.micro");
  const [storage, setStorage] = useState(String(db?.AllocatedStorage || 20));
  const [retention, setRetention] = useState(String(db?.BackupRetentionPeriod ?? 7));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (!db) return null;
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.modifyDBInstance(db.DBInstanceIdentifier, {
        DBInstanceClass: cls, AllocatedStorage: Number(storage), BackupRetentionPeriod: Number(retention),
      });
      notify.success(`Modifying "${db.DBInstanceIdentifier}".`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={`Modify ${db.DBInstanceIdentifier}`} size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Continue</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="DB instance class">
          <Select selectedOption={INSTANCE_CLASSES.find((c) => c.value === cls) || { value: cls, label: cls }}
            onChange={({ detail }) => setCls(detail.selectedOption.value)} options={INSTANCE_CLASSES} ariaLabel="DB instance class" />
        </FormField>
        <FormField label="Allocated storage (GiB)"><Input type="number" value={storage} onChange={({ detail }) => setStorage(detail.value)} ariaLabel="Allocated storage" /></FormField>
        <FormField label="Backup retention period (days)"><Input type="number" value={retention} onChange={({ detail }) => setRetention(detail.value)} ariaLabel="Backup retention period" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

export function SnapshotModal({ dbId, visible, onDismiss, notify }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (visible && dbId) setName(`${dbId}-${new Date().toISOString().slice(0, 10)}`); }, [visible, dbId]);
  return (
    <Modal visible={visible} onDismiss={() => { onDismiss(); setName(""); }} header="Take snapshot"
      footer={<Box float="right"><Button variant="primary" loading={busy} onClick={async () => {
        setBusy(true);
        try { await api.createDBSnapshot(dbId, name); notify.success(`Taking snapshot "${name}".`); }
        catch (e) { notify.error(e); }
        setBusy(false); onDismiss(); setName("");
      }}>Take snapshot</Button></Box>}>
      <FormField label="Snapshot name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Snapshot name" /></FormField>
    </Modal>
  );
}

export function DeleteDatabaseModal({ dbIds, visible, onDismiss, onDone, notify }) {
  const [finalSnapshot, setFinalSnapshot] = useState(false);
  const [snapName, setSnapName] = useState(dbIds.length === 1 ? `${dbIds[0]}-final-snapshot` : "");
  return (
    <DeleteModal
      visible={visible}
      resourceType="database"
      names={dbIds}
      onDismiss={onDismiss}
      warning="Deleting a database is permanent. Unless you create a final snapshot, the data cannot be recovered."
      onConfirm={async () => {
        for (const id of dbIds) {
          await api.deleteDBInstance(id, {
            skipFinalSnapshot: !finalSnapshot,
            finalSnapshotId: finalSnapshot ? (dbIds.length === 1 ? snapName : `${id}-final-snapshot`) : undefined,
          });
        }
        notify.success(`Deletion of ${dbIds.length === 1 ? `"${dbIds[0]}"` : `${dbIds.length} databases`} has started.`);
        onDone();
      }}
    >
      <Checkbox checked={finalSnapshot} onChange={({ detail }) => setFinalSnapshot(detail.checked)}>Create final snapshot</Checkbox>
      {finalSnapshot && dbIds.length === 1 && (
        <FormField label="Final snapshot name"><Input value={snapName} onChange={({ detail }) => setSnapName(detail.value)} ariaLabel="Final snapshot name" /></FormField>
      )}
    </DeleteModal>
  );
}
