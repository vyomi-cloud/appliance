import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { getExploreSettings, setExploreSettings } from "./prefs.js";

export default function EditExploreItemsSettings() {
  const notify = useNotify();
  const [v, setV] = useState(getExploreSettings);

  const submit = () => {
    setExploreSettings(v);
    notify.success("Explore items settings saved.");
    navigate("dynamodb", "settings");
  };

  return (
    <ContentLayout header={<Header variant="h1">Edit explore items settings</Header>}>
      <Form actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" href="#/dynamodb/settings" onFollow={follow}>Cancel</Button>
          <Button variant="primary" onClick={submit}>Save changes</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">Explore items settings</Header>}>
          <SpaceBetween size="l">
            <FormField label="Default query type">
              <RadioGroup value={v.defaultQueryType} onChange={({ detail }) => setV({ ...v, defaultQueryType: detail.value })}
                items={[{ value: "Scan", label: "Scan" }, { value: "Query", label: "Query" }]} />
            </FormField>
            <FormField label="Default item editor view">
              <RadioGroup value={v.defaultItemEditorView} onChange={({ detail }) => setV({ ...v, defaultItemEditorView: detail.value })}
                items={[{ value: "Form view", label: "Form view" }, { value: "JSON view", label: "JSON view" }]} />
            </FormField>
            <FormField label="Default JSON view syntax">
              <RadioGroup value={v.defaultJsonSyntax} onChange={({ detail }) => setV({ ...v, defaultJsonSyntax: detail.value })}
                items={[{ value: "DynamoDB JSON", label: "DynamoDB JSON" }, { value: "JSON", label: "JSON" }]} />
            </FormField>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
}
