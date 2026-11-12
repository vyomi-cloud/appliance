/* "Subscribe to Amazon SNS topic" — a real sns:Subscribe (Protocol=sqs) call, exactly
 * what the AWS console's SQS "Subscribe to Amazon SNS topic" action does. */
import { useState } from "react";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function SnsSubscribeModal({ visible, queueArn, onDismiss, onDone }) {
  const topics = useAsync(() => (visible ? api.listTopics() : Promise.resolve([])), [visible]);
  const [topicArn, setTopicArn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.subscribeQueueToTopic(topicArn, queueArn);
      onDone(); onDismiss(); setTopicArn("");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Subscribe to Amazon SNS topic"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!topicArn} onClick={submit}>Save</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Topic" description="Choose the SNS topic that will deliver messages to this queue.">
          <Select
            selectedOption={topicArn ? { value: topicArn, label: topicArn } : null}
            onChange={({ detail }) => setTopicArn(detail.selectedOption.value)}
            loadingText="Loading topics" statusType={topics.loading ? "loading" : "finished"}
            placeholder="Choose an SNS topic"
            options={(topics.data || []).map((arn) => ({ value: arn, label: arn }))}
            ariaLabel="Topic"
          />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}
