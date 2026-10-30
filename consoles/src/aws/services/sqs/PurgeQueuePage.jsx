/* Purge queue — its own confirmation page, like the console's "purge" modal. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Alert from "@cloudscape-design/components/alert";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function PurgeQueuePage({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (typed !== "purge") return;
    setBusy(true); setError(null);
    try {
      const url = await api.getQueueUrl(name);
      await api.purgeQueue(url);
      notify.success(`Successfully purged queue "${name}".`);
      location.hash = href("sqs", "queues", name).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Purge queue</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Purge queue</Header>}>
          <SpaceBetween size="m">
            <Box variant="span">Permanently delete all messages in queue <b>{name}</b>? You can't undo this action.</Box>
            <Alert type="warning">All of the messages in the queue will be deleted.</Alert>
            {error && <ErrorAlert error={error} />}
            <FormField label={<span>To confirm deletion, type <i>purge</i> in the text input field.</span>}>
              <Input value={typed} placeholder="purge" onChange={({ detail }) => setTyped(detail.value)} ariaLabel="Confirm purge queue" />
            </FormField>
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" href={href("sqs", "queues", name)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={typed !== "purge"} onClick={submit}>Purge</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
