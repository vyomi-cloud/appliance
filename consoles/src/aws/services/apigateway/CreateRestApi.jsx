import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const ENDPOINT_TYPES = [{ value: "REGIONAL", label: "Regional" }, { value: "EDGE", label: "Edge-optimized" }, { value: "PRIVATE", label: "Private" }];

export default function CreateRestApi() {
  const notify = useNotify();
  const [source, setSource] = useState("New API");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [endpointType, setEndpointType] = useState(ENDPOINT_TYPES[0]);
  const [ipAddressType, setIpAddressType] = useState("ipv4");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const created = await api.createRestApi({
        name, description, ipAddressType,
        endpointConfiguration: { types: [endpointType.value] },
      });
      notify.success(`API "${name}" created.`);
      navigate("apigateway", "apis", created.id);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create REST API</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} header="Couldn't create API" />}
        <Container header={<Header variant="h2">API details</Header>}>
          <SpaceBetween size="l">
            <FormField label="API details">
              <RadioGroup value={source} onChange={({ detail }) => setSource(detail.value)}
                items={["New API", "Clone existing API", "Import API", "Example API"].map((v) => ({ value: v, label: v, disabled: v !== "New API" }))} />
            </FormField>
            <FormField label="API name" constraintText="Required">
              <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="My REST API" ariaLabel="API name" />
            </FormField>
            <FormField label="Description - optional">
              <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
            </FormField>
            <FormField label="API endpoint type">
              <Select selectedOption={endpointType} onChange={({ detail }) => setEndpointType(detail.selectedOption)} options={ENDPOINT_TYPES} />
            </FormField>
            <FormField label="IP address type">
              <RadioGroup value={ipAddressType} onChange={({ detail }) => setIpAddressType(detail.value)}
                items={[{ value: "ipv4", label: "IPv4" }, { value: "dualstack", label: "Dualstack" }]} />
            </FormField>
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("apigateway", "apis")}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create API</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
