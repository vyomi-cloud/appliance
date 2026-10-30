import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Toggle from "@cloudscape-design/components/toggle";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const METHOD_TYPES = ["ANY", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"];
const INTEG_OPTIONS = [
  { value: "Lambda function", label: "Lambda function" }, { value: "HTTP", label: "HTTP" }, { value: "Mock", label: "Mock" },
  { value: "AWS service", label: "AWS service", disabled: true }, { value: "VPC link", label: "VPC link", disabled: true },
];

export default function CreateMethod({ params }) {
  const { id: apiId, resId } = params;
  const notify = useNotify();
  const fns = useAsync(() => api.listLambdaFunctions(), []);
  const [methodType, setMethodType] = useState({ value: "GET", label: "GET" });
  const [integType, setIntegType] = useState("Lambda function");
  const [lambdaProxy, setLambdaProxy] = useState(true);
  const [lambdaFn, setLambdaFn] = useState(null);
  const [endpointUrl, setEndpointUrl] = useState("");
  const [timeout_, setTimeout_] = useState("29000");
  const [authorization, setAuthorization] = useState({ value: "NONE", label: "None" });
  const [apiKeyRequired, setApiKeyRequired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.putMethod(apiId, resId, methodType.value, { authorizationType: authorization.value, apiKeyRequired });
      const common = { timeoutInMillis: Number(timeout_) || 29000 };
      if (integType === "Lambda function") {
        await api.putIntegration(apiId, resId, methodType.value, {
          ...common, type: lambdaProxy ? "AWS_PROXY" : "AWS",
          uri: `arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:000000000000:function:${lambdaFn?.value}/invocations`,
        });
      } else if (integType === "HTTP") {
        await api.putIntegration(apiId, resId, methodType.value, { ...common, type: "HTTP_PROXY", uri: endpointUrl, integrationHttpMethod: methodType.value === "ANY" ? "GET" : methodType.value });
      } else {
        await api.putIntegration(apiId, resId, methodType.value, { ...common, type: "MOCK", mockStatus: 200, mockBody: JSON.stringify({ message: "ok" }) });
      }
      notify.success(`Method ${methodType.value} created.`);
      navigate("apigateway", "apis", apiId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create method</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} header="Couldn't create method" />}
        <Container header={<Header variant="h2">Method details</Header>}>
          <SpaceBetween size="l">
            <FormField label="Method type"><Select selectedOption={methodType} onChange={({ detail }) => setMethodType(detail.selectedOption)} options={METHOD_TYPES.map((m) => ({ value: m, label: m }))} /></FormField>
            <FormField label="Integration type"><RadioGroup value={integType} onChange={({ detail }) => setIntegType(detail.value)} items={INTEG_OPTIONS} /></FormField>
            {integType === "Lambda function" && (
              <>
                <FormField label="Lambda proxy integration"><Toggle checked={lambdaProxy} onChange={({ detail }) => setLambdaProxy(detail.checked)}>Use Lambda proxy integration</Toggle></FormField>
                <FormField label="Lambda function" constraintText="Required">
                  <Select selectedOption={lambdaFn} onChange={({ detail }) => setLambdaFn(detail.selectedOption)} placeholder="Choose a Lambda function"
                    options={(fns.data || []).map((f) => ({ value: f.FunctionName, label: f.FunctionName }))} />
                </FormField>
              </>
            )}
            {integType === "HTTP" && <FormField label="Endpoint URL"><Input value={endpointUrl} onChange={({ detail }) => setEndpointUrl(detail.value)} placeholder="https://example.com/path" ariaLabel="Endpoint URL" /></FormField>}
            <FormField label="Integration timeout"><Input type="number" value={timeout_} onChange={({ detail }) => setTimeout_(detail.value)} ariaLabel="Integration timeout" /></FormField>
          </SpaceBetween>
        </Container>
        <ExpandableSection headerText="Method request settings" defaultExpanded>
          <SpaceBetween size="l">
            <FormField label="Authorization"><Select selectedOption={authorization} onChange={({ detail }) => setAuthorization(detail.selectedOption)} options={[{ value: "NONE", label: "None" }, { value: "AWS_IAM", label: "AWS_IAM" }]} /></FormField>
            <FormField label="API key required"><Checkbox checked={apiKeyRequired} onChange={({ detail }) => setApiKeyRequired(detail.checked)}>API key required</Checkbox></FormField>
          </SpaceBetween>
        </ExpandableSection>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("apigateway", "apis", apiId)}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={integType === "Lambda function" && !lambdaFn} onClick={submit}>Create method</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </ContentLayout>
  );
}
