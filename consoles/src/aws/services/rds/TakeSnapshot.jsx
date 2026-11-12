import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function TakeSnapshot() {
  const notify = useNotify();
  const dbs = useAsync(() => api.describeDBInstances());
  const [snapType, setSnapType] = useState("DB instance");
  const [instanceId, setInstanceId] = useState("");
  const [name, setName] = useState("");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createDBSnapshot(instanceId, name, tags.filter((t) => t.key).map((t) => ({ Key: t.key, Value: t.value || "" })));
      notify.success(`Taking snapshot "${name}".`);
      navigate("rds", "snapshots");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Take DB snapshot</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href={href("rds", "snapshots")} onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy} disabled={!instanceId || !name}>Take snapshot</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Settings</Header>}>
              <SpaceBetween size="l">
                <FormField label="Snapshot type">
                  <RadioGroup value={snapType} onChange={({ detail }) => setSnapType(detail.value)} items={[{ value: "DB instance", label: "DB instance" }, { value: "DB cluster", label: "DB cluster" }]} />
                </FormField>
                <FormField label="DB instance">
                  <Select selectedOption={instanceId ? { value: instanceId, label: instanceId } : null}
                    onChange={({ detail }) => setInstanceId(detail.selectedOption.value)} placeholder="Choose a DB instance"
                    options={(dbs.data || []).map((d) => ({ value: d.DBInstanceIdentifier, label: d.DBInstanceIdentifier }))} ariaLabel="DB instance" />
                </FormField>
                <FormField label="Snapshot name">
                  <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Snapshot name" />
                </FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2">Tags</Header>}>
              <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} />
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
