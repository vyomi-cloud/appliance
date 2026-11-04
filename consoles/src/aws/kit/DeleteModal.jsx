/* Delete confirmation with the console's type-to-confirm pattern. */
import { useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Alert from "@cloudscape-design/components/alert";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";

export default function DeleteModal({ visible, onDismiss, onConfirm, resourceType, names = [], confirmText, warning, children }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const need = confirmText ?? (names.length === 1 ? names[0] : "delete");
  const close = () => { setTyped(""); setError(null); onDismiss(); };
  const go = async () => {
    setBusy(true); setError(null);
    try { await onConfirm(); setTyped(""); onDismiss(); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Modal
      visible={visible}
      onDismiss={close}
      header={`Delete ${names.length > 1 ? `${names.length} ${resourceType}s` : resourceType}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={close}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={typed !== need} onClick={go}>Delete</Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Box variant="span">
          Permanently delete {names.length === 1 ? <b>{names[0]}</b> : <b>{names.length} {resourceType}s</b>}? You can't undo this action.
        </Box>
        {warning && <Alert type="warning">{warning}</Alert>}
        {children}
        {error && <Alert type="error" header={error.code}>{error.message}</Alert>}
        <FormField label={<span>To confirm deletion, enter <i>{need}</i> in the text input field.</span>}>
          <Input value={typed} placeholder={need} onChange={({ detail }) => setTyped(detail.value)} ariaLabel="Confirm deletion" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}
