/* Empty bucket — its own confirmation page, like the console. Deletes every real object
 * (recursive key listing + DeleteObject per key), not just whatever the Objects tab had
 * already loaded. */
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

const PHRASE = "permanently delete";

export default function EmptyBucketPage({ params }) {
  const bucket = params.bucket;
  const notify = useNotify();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (typed !== PHRASE) return;
    setBusy(true); setError(null);
    try {
      const keys = await api.listAllObjectKeys(bucket);
      for (const key of keys) await api.deleteObject(bucket, key);
      notify.success(`Successfully emptied bucket "${bucket}". ${keys.length} object${keys.length === 1 ? "" : "s"} deleted.`);
      location.hash = href("s3", "buckets", bucket).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Empty bucket</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Permanently delete all objects in bucket</Header>}>
          <SpaceBetween size="m">
            <Box variant="span">Emptying the bucket <b>{bucket}</b> will permanently delete <b>ALL</b> objects and their versions inside it. This action cannot be undone.</Box>
            <Alert type="warning">This will permanently delete all objects in this bucket. You can't undo this action.</Alert>
            {error && <ErrorAlert error={error} />}
            <FormField label="To confirm deletion, type permanently delete in the text input field.">
              <Input value={typed} placeholder={PHRASE} onChange={({ detail }) => setTyped(detail.value)} ariaLabel="Confirm empty bucket" />
            </FormField>
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" href={href("s3", "buckets", bucket)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={typed !== PHRASE} onClick={submit}>Empty</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
