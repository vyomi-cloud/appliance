/* "Configure Lambda function trigger" — a real CreateEventSourceMapping (EventSourceType
 * SQS) against this queue's ARN; see core/lambda_core.py invoke_trigger_mapping / sqs_core.py
 * _fire_triggers for how a message sent to the queue really invokes the function. */
import { useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function LambdaTriggerModal({ visible, queueArn, onDismiss, onDone }) {
  const fns = useAsync(() => (visible ? api.listFunctions() : Promise.resolve([])), [visible]);
  const [name, setName] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createLambdaTrigger(queueArn, name, enabled);
      onDone(); onDismiss(); setName("");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Configure Lambda function trigger"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Save</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Lambda function" description="Choose the function to invoke when a message is sent to this queue.">
          <Select
            selectedOption={name ? { value: name, label: name } : null}
            onChange={({ detail }) => setName(detail.selectedOption.value)}
            loadingText="Loading functions" statusType={fns.loading ? "loading" : "finished"}
            placeholder="Choose a function"
            options={(fns.data || []).map((f) => ({ value: f.FunctionName, label: f.FunctionName }))}
            ariaLabel="Lambda function"
          />
        </FormField>
        <Checkbox checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)}>Activate trigger</Checkbox>
      </SpaceBetween>
    </Modal>
  );
}
