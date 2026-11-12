import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateResource({ params }) {
  const { id: apiId, parentId } = params;
  const notify = useNotify();
  const resources = useAsync(() => api.listResources(apiId), [apiId]);
  const [proxy, setProxy] = useState(false);
  const [parent, setParent] = useState(null);
  const [name, setName] = useState("");
  const [cors, setCors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const options = (resources.data || []).map((r) => ({ value: r.id, label: r.path }));
  const effectiveParent = parent || options.find((o) => o.value === parentId) || options[0];

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const created = await api.createResource(apiId, effectiveParent.value, proxy ? "{proxy+}" : name);
      if (cors) await api.enableCors(apiId, created.id);
      notify.success(`Resource "${created.path}" created.`);
      navigate("apigateway", "apis", apiId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create resource</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} header="Couldn't create resource" />}
        <Container header={<Header variant="h2">Resource details</Header>}>
          <SpaceBetween size="l">
            <FormField label="Proxy resource"><Toggle checked={proxy} onChange={({ detail }) => setProxy(detail.checked)}>Configure as proxy resource</Toggle></FormField>
            <FormField label="Resource path"><Select selectedOption={effectiveParent} onChange={({ detail }) => setParent(detail.selectedOption)} options={options} /></FormField>
            {!proxy && <FormField label="Resource name" constraintText="Required"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Resource name" /></FormField>}
            <FormField label="CORS (Cross Origin Resource Sharing)"><Checkbox checked={cors} onChange={({ detail }) => setCors(detail.checked)}>Enable API Gateway CORS</Checkbox></FormField>
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("apigateway", "apis", apiId)}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!proxy && !name} onClick={submit}>Create resource</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
