import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateApiKey() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState("Auto generate");
  const [custom, setCustom] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const created = await api.createApiKey({
        name, description, enabled: true,
        value: mode === "Custom" ? custom : undefined,
        tags: Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value || ""])),
      });
      notify.success(`API key "${created.name}" created.`);
      navigate("apigateway", "api-keys");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create API key</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} header="Couldn't create API key" />}
        <Container header={<Header variant="h2">API key details</Header>}>
          <SpaceBetween size="l">
            <FormField label="Name" constraintText="Required"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
            <FormField label="Description - optional"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
            <FormField label="API key">
              <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)} items={[{ value: "Auto generate", label: "Auto generate" }, { value: "Custom", label: "Custom" }]} />
            </FormField>
            {mode === "Custom" && <FormField label="Value" constraintText="At least 20 characters"><Input value={custom} onChange={({ detail }) => setCustom(detail.value)} ariaLabel="API key value" /></FormField>}
            <FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} /></FormField>
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("apigateway", "api-keys")}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!name || (mode === "Custom" && custom.length < 20)} onClick={submit}>Save</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
