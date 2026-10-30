/* Console preferences, stored locally (the real Settings page is account-level opt-ins
 * for cross-service dashboards and alarm defaults — no spec fields were captured for it). */
import { useState } from "react";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useNotify } from "../../../common/notify.jsx";

const KEY = "vyomi.cloudwatch.settings";
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };

const REFRESH_OPTIONS = [{ label: "Off", value: "off" }, { label: "10 seconds", value: "10" }, { label: "1 minute", value: "60" }, { label: "5 minutes", value: "300" }];

export default function Settings() {
  const notify = useNotify();
  const [prefs, setPrefs] = useState(() => ({ autoRefresh: "off", utcTimezone: true, ...load() }));

  const save = (next) => {
    setPrefs(next);
    localStorage.setItem(KEY, JSON.stringify(next));
    notify.success("Settings saved.");
  };

  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <Container header={<Header variant="h2">Dashboard and console preferences</Header>}>
        <SpaceBetween size="l">
          <FormField label="Default dashboard auto-refresh" description="Applies to dashboards and the metrics graph while you have them open.">
            <Select
              selectedOption={REFRESH_OPTIONS.find((o) => o.value === prefs.autoRefresh)}
              onChange={({ detail }) => save({ ...prefs, autoRefresh: detail.selectedOption.value })}
              options={REFRESH_OPTIONS}
              ariaLabel="Default dashboard auto-refresh"
            />
          </FormField>
          <FormField label="Display timestamps in UTC">
            <Toggle checked={prefs.utcTimezone} onChange={({ detail }) => save({ ...prefs, utcTimezone: detail.checked })}>
              Use UTC timezone
            </Toggle>
          </FormField>
        </SpaceBetween>
      </Container>
    </ContentLayout>
  );
}
