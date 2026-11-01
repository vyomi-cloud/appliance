/* Create association — real CreateAssociation against an existing document. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateAssociation() {
  const notify = useNotify();
  const docs = useAsync(() => api.listDocuments(), []);
  const [doc, setDoc] = useState(null);
  const [associationName, setAssociationName] = useState("");
  const [instanceIds, setInstanceIds] = useState("");
  const [schedule, setSchedule] = useState("rate(14 days)");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);
  const docOptions = (docs.data || []).map((d) => ({ value: d.Name, label: d.Name }));
  const ids = instanceIds.split(",").map((s) => s.trim()).filter(Boolean);

  const submit = async () => {
    setTouched(true);
    if (!doc || !ids.length) return;
    setBusy(true); setError(null);
    try {
      const a = await api.createAssociation({
        Name: doc.value, Targets: [{ Key: "InstanceIds", Values: ids }],
        ...(associationName ? { AssociationName: associationName } : {}),
        ...(schedule ? { ScheduleExpression: schedule } : {}),
      });
      notify.success(`Association "${a.AssociationId}" created.`);
      navigate("ssm", "associations", a.AssociationId);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create association</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button formAction="none" variant="link" href="#/ssm/associations" onFollow={follow}>Cancel</Button>
              <Button variant="primary" loading={busy}>Create association</Button>
            </SpaceBetween>
          }
          errorText={error && <ErrorAlert error={error} />}
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Document</Header>}>
              <SpaceBetween size="l">
                <FormField label="Document" errorText={touched && !doc ? "Choose a document." : null}>
                  <Select selectedOption={doc} onChange={({ detail }) => setDoc(detail.selectedOption)} options={docOptions}
                    loadingText="Loading documents" statusType={docs.loading ? "loading" : "finished"} placeholder="Choose a document" />
                </FormField>
                <FormField label="Association name - optional"><Input value={associationName} onChange={({ detail }) => setAssociationName(detail.value)} /></FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2">Targets</Header>}>
              <FormField label="Instance IDs" errorText={touched && !ids.length ? "Enter at least one instance ID." : null} constraintText="Comma-separated.">
                <Input value={instanceIds} placeholder="i-0123456789abcdef0" onChange={({ detail }) => setInstanceIds(detail.value)} onBlur={() => setTouched(true)} ariaLabel="Instance IDs" />
              </FormField>
            </Container>
            <Container header={<Header variant="h2">Specify schedule</Header>}>
              <FormField label="Schedule - optional" constraintText="A rate() or cron() expression. Leave blank to run only when targets change.">
                <Input value={schedule} onChange={({ detail }) => setSchedule(detail.value)} ariaLabel="Schedule" />
              </FormField>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
