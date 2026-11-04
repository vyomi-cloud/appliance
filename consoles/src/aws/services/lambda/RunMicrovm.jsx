import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function RunMicrovm() {
  const notify = useNotify();
  const images = useAsync(() => api.listMicrovmImages(), []);
  const [image, setImage] = useState(null);
  const [role, setRole] = useState("No role");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!image) return;
    setBusy(true); setError(null);
    try {
      await api.runMicrovm({ MicrovmImage: image.value });
      notify.success("Successfully started MicroVM");
      navigate("lambda", "microvms");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  const imageOptions = (images.data || []).map((i) => ({ value: i.Name, label: i.Name }));

  return (
    <ContentLayout header={<Header variant="h1">Run MicroVM</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/lambda/microvms" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Run</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">MicroVM configuration</Header>}>
              <SpaceBetween size="l">
                <FormField label="Base MicroVM Image">
                  <Select selectedOption={image} onChange={({ detail }) => setImage(detail.selectedOption)}
                    options={imageOptions} placeholder="Choose a MicroVM image" />
                </FormField>
                <FormField label="Version"><Select selectedOption={null} onChange={() => {}} options={[]} disabled /></FormField>
                <FormField label="Execution role">
                  <RadioGroup value={role} onChange={({ detail }) => setRole(detail.value)} items={[
                    { value: "No role", label: "No role" },
                    { value: "Use a role", label: "Use a role" },
                  ]} />
                </FormField>
              </SpaceBetween>
            </Container>
            <ExpandableSection headerText="Operational settings - optional" />
            <ExpandableSection headerText="Additional configurations - optional" />
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
