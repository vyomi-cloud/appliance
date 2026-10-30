import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { getLayoutSettings, setLayoutSettings, applyContentDensity } from "./prefs.js";

const TABLE_TABS = ["Settings", "Indexes", "Monitor", "Global tables", "Backups", "Exports and streams", "Permissions"];

export default function EditLayoutSettings() {
  const notify = useNotify();
  const [v, setV] = useState(getLayoutSettings);

  const submit = () => {
    setLayoutSettings(v);
    applyContentDensity(v.density);
    notify.success("Layout and navigation settings saved.");
    navigate("dynamodb", "settings");
  };

  return (
    <ContentLayout header={<Header variant="h1">Edit layout and navigation settings</Header>}>
      <Form actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" href="#/dynamodb/settings" onFollow={follow}>Cancel</Button>
          <Button variant="primary" onClick={submit}>Save changes</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">Layout and navigation settings</Header>}>
          <SpaceBetween size="l">
            <FormField label="Content density">
              <RadioGroup value={v.density} onChange={({ detail }) => setV({ ...v, density: detail.value })}
                items={[{ value: "Comfortable", label: "Comfortable" }, { value: "Compact", label: "Compact" }]} />
            </FormField>
            <FormField label="Default entry page">
              <RadioGroup value={v.defaultEntryPage} onChange={({ detail }) => setV({ ...v, defaultEntryPage: detail.value })}
                items={[{ value: "Dashboard", label: "Dashboard" }, { value: "Tables", label: "Tables" }, { value: "Explore items", label: "Explore items" }]} />
            </FormField>
            <FormField label="Default table tab">
              <Select selectedOption={{ value: v.defaultTableTab, label: v.defaultTableTab }}
                options={TABLE_TABS.map((t) => ({ value: t, label: t }))}
                onChange={({ detail }) => setV({ ...v, defaultTableTab: detail.selectedOption.value })} ariaLabel="Default table tab" />
            </FormField>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
}
