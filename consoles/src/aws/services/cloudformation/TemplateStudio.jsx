/* Template studio — the template text editor + Validate are real (ValidateTemplate);
 * the visual resource Canvas is the declared gap (core/capabilities/aws/cloudformation.json:
 * aws.cloudformation.template-studio). "Save and continue" hands the template to
 * Create stack's file-upload step (sessionStorage is the simplest honest bridge — no
 * server-side "saved templates" store exists, so nothing claims to persist beyond this
 * browser tab). */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import * as api from "./api.js";

const DEFAULT_TEMPLATE = 'AWSTemplateFormatVersion: "2010-09-09"\nResources: {}\n';

export default function TemplateStudio() {
  const notify = useNotify();
  const [view, setView] = useState("Both");
  const [format, setFormat] = useState({ value: "YAML", label: "YAML" });
  const [text, setText] = useState(DEFAULT_TEMPLATE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const validate = async () => {
    setBusy(true); setError(null); setResult(null);
    try { const r = await api.validateTemplate(text); setResult(r); notify.success("Template is valid."); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button loading={busy} onClick={validate}>Validate</Button>
          <Button variant="primary" onClick={() => { sessionStorage.setItem("vyomi-cfn-template", text); notify.success("Template saved for this browser session — paste it in Create stack's file upload step."); }}>Save and continue</Button>
        </SpaceBetween>
      }>Template studio</Header>
    }>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<ButtonDropdown items={[{ id: "format", text: "Convert format" }, { id: "clear", text: "Clear template" }]}
          onItemClick={({ detail }) => { if (detail.id === "clear") setText(""); }}>Actions</ButtonDropdown>}>Template</Header>}>
          <SpaceBetween size="l">
            <SpaceBetween direction="horizontal" size="l">
              <FormField label="View">
                <RadioGroup value={view} onChange={({ detail }) => setView(detail.value)} items={[
                  { value: "Template", label: "Template" }, { value: "Canvas", label: "Canvas" }, { value: "Both", label: "Both" },
                ]} />
              </FormField>
              <FormField label="Format">
                <Select selectedOption={format} onChange={({ detail }) => setFormat(detail.selectedOption)}
                  options={[{ value: "YAML", label: "YAML" }, { value: "JSON", label: "JSON" }]} />
              </FormField>
            </SpaceBetween>
            <SpaceBetween direction="horizontal" size="l">
              {view !== "Canvas" && (
                <Box flex="1">
                  <FormField label="Template editor">
                    <Textarea rows={18} value={text} onChange={({ detail }) => setText(detail.value)} spellcheck={false} ariaLabel="Template editor" />
                  </FormField>
                </Box>
              )}
              {view !== "Template" && <Box flex="1"><NotSimulated feature="Canvas" note="The drag-and-drop visual resource graph isn't modeled by Vyomi — use the text editor." /></Box>}
            </SpaceBetween>
            {error && <ErrorAlert error={error} header="Template is invalid" />}
            {result && (
              <Box variant="code">
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(result, null, 2)}</pre>
              </Box>
            )}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
