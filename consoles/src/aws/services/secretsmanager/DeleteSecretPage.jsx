/* Schedule secret deletion — its own page, like the console's modal. A real scheduled
 * deletion: GetSecretValue is blocked until restored or the window elapses. */
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
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function DeleteSecretPage({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [days, setDays] = useState("30");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const n = Number(days);
  const valid = Number.isInteger(n) && n >= 7 && n <= 30;

  const submit = async () => {
    if (!valid) return;
    setBusy(true); setError(null);
    try {
      await api.deleteSecret(name, n);
      notify.success(`Successfully scheduled deletion for "${name}".`);
      navigate("secretsmanager", "secret", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Schedule secret deletion</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Schedule secret deletion</Header>}>
          <SpaceBetween size="m">
            <Box variant="span">Secrets Manager will schedule deletion of secret <b>{name}</b>. You can restore it any time before the waiting period ends.</Box>
            <Alert type="warning">You can't retrieve this secret's value once deletion is scheduled, until it's restored.</Alert>
            {error && <ErrorAlert error={error} />}
            <FormField label="Waiting period (in days)" constraintText="Enter a number between 7 and 30." errorText={!valid ? "Enter a number between 7 and 30." : null}>
              <Input type="number" value={days} onChange={({ detail }) => setDays(detail.value)} ariaLabel="Waiting period (in days)" />
            </FormField>
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" href={href("secretsmanager", "secret", name)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!valid} onClick={submit}>Schedule deletion</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
