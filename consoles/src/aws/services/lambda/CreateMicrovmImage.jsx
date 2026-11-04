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
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateMicrovmImage() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [baseImage] = useState("al2023-1");
  const [baseImageVersion] = useState("Always use latest - recommended");
  const [instanceSize, setInstanceSize] = useState("");
  const [s3Dest, setS3Dest] = useState("");
  const [permissions, setPermissions] = useState("Create default role");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createMicrovmImage({ Name: name, Description: description });
      notify.success(`Successfully created MicroVM image "${name}"`);
      navigate("lambda", "microvm-images");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create MicroVM Image</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/lambda/microvm-images" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">MicroVM Image settings</Header>}>
              <SpaceBetween size="l">
                <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
                <FormField label="Description - optional"><Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
                <FormField label="Base MicroVM Image"><Select selectedOption={{ value: baseImage, label: baseImage }} options={[{ value: baseImage, label: baseImage }]} onChange={() => {}} /></FormField>
                <FormField label="Base Image version"><Select selectedOption={{ value: baseImageVersion, label: baseImageVersion }} options={[{ value: baseImageVersion, label: baseImageVersion }]} onChange={() => {}} /></FormField>
                <FormField label="Instance size"><Input value={instanceSize} onChange={({ detail }) => setInstanceSize(detail.value)} ariaLabel="Instance size" /></FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2">Code configuration</Header>}>
              <FormField label="S3 destination">
                <Input value={s3Dest} placeholder="s3://<bucket>/<object-path>" onChange={({ detail }) => setS3Dest(detail.value)} ariaLabel="S3 destination" />
              </FormField>
            </Container>
            <Container header={<Header variant="h2">Image build configuration</Header>}>
              <FormField label="IAM permissions">
                <RadioGroup value={permissions} onChange={({ detail }) => setPermissions(detail.value)} items={[
                  { value: "Create default role", label: "Create default role" },
                  { value: "Use another role", label: "Use another role" },
                ]} />
              </FormField>
            </Container>
            <Container header={<Header variant="h2">Tags</Header>}>
              <FormField label="Tags" description="Key / Value pairs; up to 50 tags">
                <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)}
                  i18nStrings={{ addButton: "Add new tag", removeButton: "Remove", keyHeader: "Key", valueHeader: "Value", emptyTags: "No tags associated with the resource." }} />
              </FormField>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
