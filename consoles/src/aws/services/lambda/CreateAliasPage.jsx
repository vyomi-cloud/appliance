import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateAliasPage({ params }) {
  const name = params.name;
  const notify = useNotify();
  const versions = useAsync(() => api.listVersions(name), [name]);
  const [aliasName, setAliasName] = useState("");
  const [description, setDescription] = useState("");
  const [version, setVersion] = useState(null);
  const [weighted, setWeighted] = useState(false);
  const [altVersion, setAltVersion] = useState(null);
  const [weight, setWeight] = useState("10");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const opts = (versions.data || []).map((v) => ({ value: v.Version, label: v.Version }));

  const submit = async () => {
    if (!aliasName.trim() || !version) return;
    setBusy(true); setError(null);
    try {
      await api.createAlias(name, {
        Name: aliasName, FunctionVersion: version.value, Description: description,
        RoutingConfig: weighted && altVersion ? { AdditionalVersionWeights: { [altVersion.value]: Number(weight) / 100 } } : undefined,
      });
      notify.success(`Successfully created alias "${aliasName}"`);
      location.hash = `${href("lambda", "functions", name).slice(1)}?tab=aliases`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create alias</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={<SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={`#/lambda/functions/${encodeURIComponent(name)}?tab=aliases`} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Save</Button>
          </SpaceBetween>}
          errorText={error && <ErrorAlert error={error} />}
        >
          <Container header={<Header variant="h2">Alias configuration</Header>}>
            <SpaceBetween size="l">
              <FormField label="Name"><Input value={aliasName} onChange={({ detail }) => setAliasName(detail.value)} ariaLabel="Name" /></FormField>
              <FormField label="Description"><Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" /></FormField>
              <FormField label="Version">
                <Select selectedOption={version} onChange={({ detail }) => setVersion(detail.selectedOption)} options={opts} placeholder="Choose a version" />
              </FormField>
              <FormField label="Weighted alias" description="Additional version + weight (%)">
                <SpaceBetween size="s">
                  <Checkbox checked={weighted} onChange={({ detail }) => setWeighted(detail.checked)}>Add weighted alias</Checkbox>
                  {weighted && (
                    <SpaceBetween direction="horizontal" size="s">
                      <Select selectedOption={altVersion} onChange={({ detail }) => setAltVersion(detail.selectedOption)} options={opts} placeholder="Additional version" />
                      <Input type="number" value={weight} onChange={({ detail }) => setWeight(detail.value)} ariaLabel="Weight percent" />
                    </SpaceBetween>
                  )}
                </SpaceBetween>
              </FormField>
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
}
