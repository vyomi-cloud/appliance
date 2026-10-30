import { useRef, useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const RUNTIMES = ["python3.12", "python3.11", "nodejs22.x", "nodejs20.x", "java21", "ruby3.3"];

export default function CreateLayer() {
  const notify = useNotify();
  const fileInput = useRef(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState("Create from a .zip file");
  const [fileName, setFileName] = useState("");
  const [fileText, setFileText] = useState("");
  const [s3Url, setS3Url] = useState("");
  const [arches, setArches] = useState({ x86_64: true, arm64: false });
  const [runtimes, setRuntimes] = useState(null);
  const [license, setLicense] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.publishLayerVersion(name, {
        Description: description,
        Content: source === "Create from a .zip file" ? { Source: fileText || `# layer ${name}` } : { S3Key: s3Url },
        CompatibleArchitectures: Object.entries(arches).filter(([, v]) => v).map(([k]) => k),
        CompatibleRuntimes: (runtimes || []).map((r) => r.value),
        LicenseInfo: license,
      });
      notify.success(`Successfully created layer "${name}"`);
      navigate("lambda", "layers");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create layer</Header>}>
      <input ref={fileInput} type="file" hidden onChange={(e) => {
        const f = e.target.files[0]; if (!f) return;
        setFileName(f.name);
        const r = new FileReader(); r.onload = () => setFileText(String(r.result || "")); r.readAsText(f);
      }} />
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/lambda/layers" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <Container header={<Header variant="h2">Layer configuration</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
              <FormField label="Description - optional"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
              <FormField label="Source code">
                <RadioGroup value={source} onChange={({ detail }) => setSource(detail.value)} items={[
                  { value: "Create from a .zip file", label: "Create from a .zip file" },
                  { value: "Create from a file in Amazon S3", label: "Create from a file in Amazon S3" },
                ]} />
              </FormField>
              {source === "Create from a .zip file" && (
                <FormField label="Choose file" description="For files larger than 10 MB, consider uploading using Amazon S3.">
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={() => fileInput.current?.click()}>Choose file</Button>
                    <span>{fileName || "No file chosen"}</span>
                  </SpaceBetween>
                </FormField>
              )}
              {source === "Create from a file in Amazon S3" && (
                <FormField label="Amazon S3 link URL">
                  <Input value={s3Url} placeholder="s3://bucket/key.zip" onChange={({ detail }) => setS3Url(detail.value)} ariaLabel="Amazon S3 link URL" />
                </FormField>
              )}
              <FormField label="Compatible architectures - optional">
                <SpaceBetween direction="horizontal" size="s">
                  <Checkbox checked={arches.x86_64} onChange={({ detail }) => setArches({ ...arches, x86_64: detail.checked })}>x86_64</Checkbox>
                  <Checkbox checked={arches.arm64} onChange={({ detail }) => setArches({ ...arches, arm64: detail.checked })}>arm64</Checkbox>
                </SpaceBetween>
              </FormField>
              <FormField label="Compatible runtimes - optional" description="Choose up to 15 runtimes.">
                <Select selectedOption={null} onChange={({ detail }) => setRuntimes([...(runtimes || []), detail.selectedOption])}
                  options={RUNTIMES.map((v) => ({ value: v, label: v }))}
                  placeholder="Search Compatible runtimes" />
              </FormField>
              <FormField label="License - optional"><Input value={license} onChange={({ detail }) => setLicense(detail.value)} ariaLabel="License" /></FormField>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
}
