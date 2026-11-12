/* Create data stream — single-page form matching the native console. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateStream() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [mode, setMode] = useState("On-demand");
  const [shards, setShards] = useState("1");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);
  const nameErr = touched && !name ? "Data stream name is required." : null;

  const submit = async () => {
    setTouched(true);
    if (!name) return;
    setBusy(true); setError(null);
    try {
      await api.createStream({
        StreamName: name,
        StreamModeDetails: { StreamMode: mode === "On-demand" ? "ON_DEMAND" : "PROVISIONED" },
        ...(mode === "Provisioned" ? { ShardCount: Number(shards) } : {}),
        ...(tags.filter((t) => !t.markedForRemoval && t.key).length
          ? { Tags: Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value || ""])) }
          : {}),
      });
      notify.success(`Data stream "${name}" is being created.`);
      navigate("kinesis", "streams", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box padding={{ top: "l" }}>
      <ContentLayout header={<Header variant="h1">Create data stream</Header>}>
        <SpaceBetween size="l">
          {error && <ErrorAlert error={error} header="Couldn't create data stream" />}
          <Container header={<Header variant="h2">Data stream configuration</Header>}>
            <SpaceBetween size="l">
              <FormField label="Data stream name" errorText={nameErr} constraintText="1-128 characters: letters, numbers, underscores, periods and hyphens">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-stream" ariaLabel="Data stream name" />
              </FormField>
              <FormField label="Capacity mode" description="On-demand scales automatically; Provisioned uses a fixed shard count you manage.">
                <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)}
                  items={[{ value: "On-demand", label: "On-demand" }, { value: "Provisioned", label: "Provisioned" }]} />
              </FormField>
              {mode === "Provisioned" && (
                <FormField label="Number of open shards" constraintText="1 to the account's open-shard limit">
                  <Input type="number" value={shards} onChange={({ detail }) => setShards(detail.value)} ariaLabel="Number of open shards" />
                </FormField>
              )}
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}>
            <FormField label="Tags">
              <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} />
            </FormField>
          </Container>
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => navigate("kinesis", "streams")}>Cancel</Button>
              <Button variant="primary" loading={busy} onClick={submit}>Create data stream</Button>
            </SpaceBetween>
          </Box>
        </SpaceBetween>
      </ContentLayout>
    </Box>
  );
}
