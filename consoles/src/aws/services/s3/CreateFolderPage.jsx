/* Create folder — its own page (not a modal), matching the Upload/Empty/Delete pages. A
 * folder is a real zero-byte PutObject with a trailing "/" key, same as the console. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Form from "@cloudscape-design/components/form";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";
import { vy } from "../../../common/VyomiMark.jsx";

export default function CreateFolderPage({ params, query }) {
  const bucket = params.bucket;
  const prefix = query.prefix || "";
  const notify = useNotify();
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [sse, setSse] = useState("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const err = touched && name.includes("/") ? "Folder names can't contain \"/\"." : touched && !name ? "Folder name is required." : null;

  const submit = async () => {
    setTouched(true);
    if (!name || name.includes("/")) return;
    setBusy(true); setError(null);
    try {
      await api.createFolder(bucket, prefix + name);
      notify.success(`Successfully created folder "${name}".`);
      location.hash = `${href("s3", "buckets", bucket).slice(1)}?prefix=${encodeURIComponent(prefix + name + "/")}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" description={`s3://${bucket}/${prefix}`}>Create folder</Header>}>
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" href={href("s3", "buckets", bucket)} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} onClick={submit}>Create folder</Button>
          </SpaceBetween>
        }
        errorText={error && <ErrorAlert error={error} />}
      >
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Folder</Header>}>
            <FormField label="Folder name" errorText={err} constraintText="Folder names can't contain &quot;/&quot;.">
              <Input value={name} onChange={({ detail }) => setName(detail.value)} onBlur={() => setTouched(true)} />
            </FormField>
          </Container>
          <Container header={<Header variant="h2">Server-side encryption</Header>}>
            <FormField label="Server-side encryption" description={vy("Folders don't hold data, so Vyomi doesn't apply a per-folder encryption key — new objects placed in it still use the bucket's default encryption.")}>
              <RadioGroup value={sse} onChange={({ detail }) => setSse(detail.value)} items={[
                { value: "none", label: "Don't specify an encryption key" },
                { value: "key", label: "Specify an encryption key", disabled: true, description: vy("Not available in Vyomi yet.") },
              ]} />
            </FormField>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
