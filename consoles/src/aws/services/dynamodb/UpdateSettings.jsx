/* DynamoDB > Settings > Update settings: the default settings the Create table form applies when you pick "Default
 * settings" (capacity mode, provisioned capacity, table class, deletion protection). Like the real console these are
 * console-side defaults for NEW tables created from the form - they do not change existing tables or SDK/CLI calls. */
import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Input from "@cloudscape-design/components/input";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { getTableDefaults, setTableDefaults } from "./prefs.js";

export default function UpdateSettings() {
  const notify = useNotify();
  const [v, setV] = useState(getTableDefaults);
  const bad = v.capacityMode === "PROVISIONED" && !(Number(v.rcu) >= 1 && Number(v.wcu) >= 1);
  const submit = () => {
    if (bad) return;
    setTableDefaults({ ...v, rcu: Number(v.rcu), wcu: Number(v.wcu) });
    notify.success("Default settings for new tables saved.");
    navigate("dynamodb", "settings");
  };
  return (
    <ContentLayout header={<Header variant="h1" info={<CapabilityBadge id="dynamodb.account.update-settings" />}>Update settings</Header>}>
      <Form actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" href="#/dynamodb/settings" onFollow={follow}>Cancel</Button>
          <Button variant="primary" disabled={bad} onClick={submit}>Save changes</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2" description="Applied when you choose Default settings on Create table.">Default settings for new tables</Header>}>
          <SpaceBetween size="l">
            <FormField label="Capacity mode">
              <RadioGroup value={v.capacityMode} onChange={({ detail }) => setV({ ...v, capacityMode: detail.value })}
                items={[{ value: "PAY_PER_REQUEST", label: "On-demand" }, { value: "PROVISIONED", label: "Provisioned" }]} />
            </FormField>
            {v.capacityMode === "PROVISIONED" && (
              <SpaceBetween direction="horizontal" size="m">
                <FormField label="Read capacity units"><Input type="number" value={String(v.rcu)} onChange={({ detail }) => setV({ ...v, rcu: detail.value })} /></FormField>
                <FormField label="Write capacity units"><Input type="number" value={String(v.wcu)} onChange={({ detail }) => setV({ ...v, wcu: detail.value })} /></FormField>
              </SpaceBetween>
            )}
            <FormField label="Table class">
              <RadioGroup value={v.tableClass} onChange={({ detail }) => setV({ ...v, tableClass: detail.value })}
                items={[{ value: "STANDARD", label: "DynamoDB Standard" }, { value: "STANDARD_INFREQUENT_ACCESS", label: "DynamoDB Standard-IA" }]} />
            </FormField>
            <Checkbox checked={v.deletionProtection} onChange={({ detail }) => setV({ ...v, deletionProtection: detail.checked })}>Turn on deletion protection</Checkbox>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
}
