/* Create patch baseline — real CreatePatchBaseline. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const OSES = ["AMAZON_LINUX_2023", "AMAZON_LINUX_2", "AMAZON_LINUX", "UBUNTU", "REDHAT_ENTERPRISE_LINUX", "SUSE", "CENTOS", "DEBIAN", "WINDOWS", "MACOS"];

export default function CreatePatchBaseline() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [os, setOs] = useState({ value: "AMAZON_LINUX_2023", label: "AMAZON_LINUX_2023" });
  const [approved, setApproved] = useState("");
  const [rejected, setRejected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  const submit = async () => {
    setTouched(true);
    if (!name) return;
    setBusy(true); setError(null);
    try {
      const { BaselineId } = await api.createPatchBaseline({
        Name: name, OperatingSystem: os.value, ...(description ? { Description: description } : {}),
        ...(approved.trim() ? { ApprovedPatches: approved.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
        ...(rejected.trim() ? { RejectedPatches: rejected.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
      });
      notify.success(`Successfully created patch baseline "${name}"`);
      navigate("ssm", "patch-baselines", BaselineId);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create patch baseline</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href="#/ssm/patch-baselines" onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy}>Create patch baseline</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <Container header={<Header variant="h2">Baseline details</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name" errorText={touched && !name ? "Enter a name." : null}>
                <Input value={name} onChange={({ detail }) => setName(detail.value)} onBlur={() => setTouched(true)} ariaLabel="Name" />
              </FormField>
              <FormField label="Description - optional"><Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} /></FormField>
              <FormField label="Operating system">
                <Select selectedOption={os} onChange={({ detail }) => setOs(detail.selectedOption)} options={OSES.map((v) => ({ value: v, label: v }))} />
              </FormField>
              <FormField label="Approved patches - optional" constraintText="Comma-separated patch IDs."><Textarea value={approved} onChange={({ detail }) => setApproved(detail.value)} /></FormField>
              <FormField label="Rejected patches - optional" constraintText="Comma-separated patch IDs."><Textarea value={rejected} onChange={({ detail }) => setRejected(detail.value)} /></FormField>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
}
