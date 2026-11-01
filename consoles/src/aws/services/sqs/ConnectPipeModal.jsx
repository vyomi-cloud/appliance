/* "Connect queue to pipe" — a real CreatePipe (Source = this queue's ARN) against
 * core/eventbridge_core.py's Pipes; see sqs_core.py _fire_triggers for how a message
 * sent to the queue is really forwarded to the pipe's Target. */
import { useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ConnectPipeModal({ visible, queueArn, onDismiss, onDone }) {
  const targets = useAsync(() => (visible ? api.listPipeTargets() : Promise.resolve([])), [visible]);
  const [name, setName] = useState("");
  const [target, setTarget] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createPipe(name, queueArn, target.value);
      onDone(); onDismiss(); setName(""); setTarget(null);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Connect queue to pipe"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !target} onClick={submit}>Create pipe</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Pipe name">
          <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Pipe name" />
        </FormField>
        <FormField label="Target" description="Every message sent to this queue is forwarded here.">
          <Select
            selectedOption={target}
            onChange={({ detail }) => setTarget(detail.selectedOption)}
            loadingText="Loading targets" statusType={targets.loading ? "loading" : "finished"}
            placeholder="Choose a target"
            options={(targets.data || []).map((t) => ({ value: t.arn, label: t.label }))}
            ariaLabel="Target"
          />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}
