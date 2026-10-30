import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { follow, navigate } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateNetworkConnector() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [computeType, setComputeType] = useState("MicroVm");
  const [vpc, setVpc] = useState("");
  const [protocol, setProtocol] = useState("");
  const [role, setRole] = useState("Create new role");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name.trim() || !vpc.trim()) return;
    setBusy(true); setError(null);
    try {
      await api.createNetworkConnector({ Name: name, AssociatedComputeType: computeType, VpcId: vpc, NetworkProtocol: protocol });
      notify.success(`Successfully created network connector "${name}"`);
      navigate("lambda", "network-connectors");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create network connector</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/lambda/network-connectors" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create network connector</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
          <Container header={<Header variant="h2">Network connector settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
              <FormField label="Associated compute type">
                <Select selectedOption={{ value: computeType, label: computeType }} onChange={({ detail }) => setComputeType(detail.selectedOption.value)}
                  options={[{ value: "MicroVm", label: "MicroVm" }]} />
              </FormField>
              <FormField label="VPC"><Input value={vpc} placeholder="Choose VPC" onChange={({ detail }) => setVpc(detail.value)} ariaLabel="VPC" /></FormField>
              <FormField label="Network protocol">
                <Select selectedOption={protocol ? { value: protocol, label: protocol } : null}
                  placeholder="Search Network protocol"
                  onChange={({ detail }) => setProtocol(detail.selectedOption.value)}
                  options={["TCP", "UDP"].map((p) => ({ value: p, label: p }))} />
              </FormField>
              <FormField label="Execution role">
                <RadioGroup value={role} onChange={({ detail }) => setRole(detail.value)} items={[
                  { value: "Choose an existing role", label: "Choose an existing role" },
                  { value: "Create new role", label: "Create new role" },
                ]} />
              </FormField>
            </SpaceBetween>
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
