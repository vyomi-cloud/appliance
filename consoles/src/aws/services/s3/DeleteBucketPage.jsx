/* Delete bucket — its own confirmation page, like the console. S3 refuses to delete a
 * non-empty bucket (real semantic kept by the backend), so a failed delete surfaces that
 * error rather than silently "succeeding". */
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

export default function DeleteBucketPage({ params }) {
  const bucket = params.bucket;
  const notify = useNotify();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (typed !== bucket) return;
    setBusy(true); setError(null);
    try {
      await api.deleteBucket(bucket);
      notify.success(`Successfully deleted bucket "${bucket}".`);
      location.hash = href("s3", "buckets").slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Delete bucket</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Delete bucket</Header>}>
          <SpaceBetween size="m">
            <Box variant="span">Permanently delete bucket <b>{bucket}</b>? You can't undo this action.</Box>
            <Alert type="warning">Buckets must be empty before they can be deleted.</Alert>
            {error && <ErrorAlert error={error} />}
            <FormField label="To confirm deletion, enter the name of the bucket in the text input field.">
              <Input value={typed} placeholder={bucket} onChange={({ detail }) => setTyped(detail.value)} ariaLabel="Confirm delete bucket" />
            </FormField>
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" href={href("s3", "buckets", bucket)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={typed !== bucket} onClick={submit}>Delete bucket</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
