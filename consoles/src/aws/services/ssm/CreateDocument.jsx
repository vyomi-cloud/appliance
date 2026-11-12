/* Create document — real CreateDocument. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const DOC_TYPES = ["Command", "Automation", "Policy", "Session", "Package", "ApplicationConfiguration", "ChangeCalendar"];
const DEFAULT_CONTENT = `{
  "schemaVersion": "2.2",
  "description": "My command document",
  "parameters": {},
  "mainSteps": []
}`;

export default function CreateDocument() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [docType, setDocType] = useState({ value: "Command", label: "Command" });
  const [format, setFormat] = useState("JSON");
  const [content, setContent] = useState(DEFAULT_CONTENT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  const submit = async () => {
    setTouched(true);
    if (!name || !content) return;
    setBusy(true); setError(null);
    try {
      await api.createDocument({ Name: name, Content: content, DocumentType: docType.value, DocumentFormat: format });
      notify.success(`Successfully created document "${name}"`);
      location.hash = `${href("ssm", "documents", "view").slice(1)}?name=${encodeURIComponent(name)}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create document</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href="#/ssm/documents" onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy}>Create document</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Document details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Name" errorText={touched && !name ? "Enter a document name." : null} constraintText="3-128 characters: a-zA-Z0-9_-.:/. Can't start with aws or amazon.">
                  <Input value={name} onChange={({ detail }) => setName(detail.value)} onBlur={() => setTouched(true)} ariaLabel="Name" />
                </FormField>
                <FormField label="Document type">
                  <Select selectedOption={docType} onChange={({ detail }) => setDocType(detail.selectedOption)} options={DOC_TYPES.map((t) => ({ value: t, label: t }))} />
                </FormField>
                <FormField label="Document format">
                  <RadioGroup value={format} onChange={({ detail }) => setFormat(detail.value)} items={[{ value: "JSON", label: "JSON" }, { value: "YAML", label: "YAML" }, { value: "TEXT", label: "TEXT" }]} />
                </FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2" description="Must include schemaVersion.">Content</Header>}>
              <FormField label="Content" errorText={touched && !content ? "Enter the document content." : null}>
                <Textarea rows={14} value={content} onChange={({ detail }) => setContent(detail.value)} onBlur={() => setTouched(true)} spellcheck={false} ariaLabel="Content" />
              </FormField>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
