import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const NAME_RE = /^[A-Za-z0-9_-]{1,255}$/;

export default function CreateDashboard() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = name && !NAME_RE.test(name) ? "Dashboard name can only contain alphanumerics, dash (-) and underscore (_)." : null;

  const submit = async () => {
    if (!name || nameErr) return;
    setBusy(true); setError(null);
    try {
      await api.putDashboard(name, { widgets: [] });
      notify.success(`Dashboard ${name} was created.`);
      navigate("cloudwatch", "dashboards", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create new dashboard</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" onClick={() => navigate("cloudwatch", "dashboards")}>Cancel</Button>
            <Button formAction="submit" variant="primary" loading={busy} disabled={!name || !!nameErr}>Create dashboard</Button>
          </SpaceBetween>}
        >
          <SpaceBetween size="l">
            {error && <ErrorAlert error={error} />}
            <Container header={<Header variant="h2">Create new dashboard</Header>}>
              <FormField label="Dashboard name" errorText={nameErr} description="Up to 255 characters: letters, numbers, dash and underscore.">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Dashboard name" autoFocus />
              </FormField>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
