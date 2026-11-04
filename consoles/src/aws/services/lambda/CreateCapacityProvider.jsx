import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Checkbox from "@cloudscape-design/components/checkbox";
import RadioGroup from "@cloudscape-design/components/radio-group";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateCapacityProvider() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [vpc, setVpc] = useState("");
  const [changeRole, setChangeRole] = useState(false);
  const [arch, setArch] = useState("x86_64");
  const [maxVcpu, setMaxVcpu] = useState("4");
  const [scalingMode, setScalingMode] = useState("Managed scaling");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim() || !vpc.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createCapacityProvider({ Name: name, VpcId: vpc, Architectures: [arch], MaximumVcpu: Number(maxVcpu) || 4, ScalingMode: scalingMode });
      notify.success(`Successfully created capacity provider "${name}"`);
      navigate("lambda", "capacity-providers");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create capacity provider</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/lambda/capacity-providers" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create capacity provider</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Capacity provider settings</Header>}>
              <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
            </Container>
            <Container header={<Header variant="h2">Network Configuration</Header>}>
              <FormField label="VPC"><Input value={vpc} placeholder="Choose VPC" onChange={({ detail }) => setVpc(detail.value)} ariaLabel="VPC" /></FormField>
            </Container>
            <Container header={<Header variant="h2">Permissions</Header>}>
              <Checkbox checked={changeRole} onChange={({ detail }) => setChangeRole(detail.checked)}>Change default operator role</Checkbox>
            </Container>
            <ExpandableSection headerText="Advanced settings" headerDescription="Architecture, instance types, scaling, encryption, tags">
              <SpaceBetween size="l">
                <FormField label="Architecture">
                  <RadioGroup value={arch} onChange={({ detail }) => setArch(detail.value)}
                    items={[{ value: "x86_64", label: "x86_64" }, { value: "arm64", label: "arm64" }]} />
                </FormField>
                <FormField label="Maximum vCPU"><Input value={maxVcpu} type="number" onChange={({ detail }) => setMaxVcpu(detail.value)} ariaLabel="Maximum vCPU" /></FormField>
                <FormField label="Scaling mode"><Input value={scalingMode} onChange={({ detail }) => setScalingMode(detail.value)} ariaLabel="Scaling mode" /></FormField>
              </SpaceBetween>
            </ExpandableSection>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
