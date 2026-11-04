/* EC2 console → Elastic Block Store → Lifecycle Manager (Amazon DLM). Native wire:
 * core/dlm_core.py's REST-JSON engine (separate "dlm" AWS service, same /_wire). An
 * ENABLED policy really creates (and prunes) snapshots/AMIs for tagged resources on
 * its schedule — see ec2.lifecycle-manager. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const opt = (v, label) => ({ value: v, label: label || v });

export function LifecycleManager() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.getLifecyclePolicies(), []);
  const rows = t.data || [];

  const toggle = async (p) => {
    await api.updateLifecyclePolicy(p.PolicyId, { State: p.State === "ENABLED" ? "DISABLED" : "ENABLED" });
    notify.success(`Policy ${p.State === "ENABLED" ? "disabled" : "enabled"}.`); t.reload();
  };

  return (
    <ContentLayout header={<Header variant="h1">Lifecycle Manager</Header>}>
      <ResourceTable
        resourceName="Lifecycle Policies"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="PolicyId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find lifecycle policies"
        empty={{ title: "No lifecycle policies", subtitle: "You don't have any Data Lifecycle Manager policies yet." }}
        columns={[
          { id: "id", header: "Policy ID", isRowHeader: true, cell: (p) => p.PolicyId },
          { id: "desc", header: "Description", cell: (p) => p.Description || "-" },
          { id: "type", header: "Policy type", cell: (p) => (p.PolicyType === "IMAGE_MANAGEMENT" ? "EBS-backed AMI policy" : "EBS snapshot policy") },
          { id: "state", header: "State", cell: (p) => <StatusIndicator type={p.State === "ENABLED" ? "success" : "stopped"}>{p.State}</StatusIndicator> },
          { id: "toggle", header: "", cell: (p) => <Button onClick={() => toggle(p)}>{p.State === "ENABLED" ? "Disable" : "Enable"}</Button> },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-lifecycle-policy")} onFollow={follow}>Create lifecycle policy</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="lifecycle policy" names={sel.map((p) => p.PolicyId)} onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const p of sel) await api.deleteLifecyclePolicy(p.PolicyId); notify.success(`${sel.length} policy(ies) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function CreateLifecyclePolicy() {
  const notify = useNotify();
  const [desc, setDesc] = useState("");
  const [resourceType, setResourceType] = useState("VOLUME");
  const [tagKey, setTagKey] = useState("Backup");
  const [tagValue, setTagValue] = useState("daily");
  const [interval, setInterval_] = useState("24");
  const [retain, setRetain] = useState("7");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createLifecyclePolicy({
        Description: desc, State: "ENABLED",
        PolicyDetails: {
          ResourceTypes: [resourceType],
          TargetTags: [{ Key: tagKey, Value: tagValue }],
          Schedules: [{ Name: "schedule-1", CreateRule: { Interval: Number(interval), IntervalUnit: "HOURS" }, RetainRule: { Count: Number(retain) } }],
        },
      });
      notify.success(`Lifecycle policy "${desc || "untitled"}" created.`);
      navigate("ec2", "lifecycle-manager");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create default policy</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "lifecycle-manager")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!tagKey || !tagValue} onClick={submit}>Create policy</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Policy description</Header>}>
            <FormField label="Description"><Input value={desc} onChange={({ detail }) => setDesc(detail.value)} placeholder="Daily volume backups" ariaLabel="Description" /></FormField>
          </Container>
          <Container header={<Header variant="h2">Target resource</Header>}>
            <SpaceBetween size="l">
              <FormField label="Policy type"><RadioGroup value={resourceType} onChange={({ detail }) => setResourceType(detail.value)} items={[
                { value: "VOLUME", label: "EBS snapshot policy" }, { value: "INSTANCE", label: "EBS-backed AMI policy" },
              ]} /></FormField>
              <FormField label="Target resource tag" description={`Only ${resourceType === "VOLUME" ? "volumes" : "instances"} with this tag are included.`}>
                <SpaceBetween size="s" direction="horizontal">
                  <Input value={tagKey} onChange={({ detail }) => setTagKey(detail.value)} placeholder="Key" ariaLabel="Tag key" />
                  <Input value={tagValue} onChange={({ detail }) => setTagValue(detail.value)} placeholder="Value" ariaLabel="Tag value" />
                </SpaceBetween>
              </FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Schedule</Header>}>
            <SpaceBetween size="l">
              <FormField label="Create every" constraintText="Hours between runs."><Input type="number" value={interval} onChange={({ detail }) => setInterval_(detail.value)} ariaLabel="Interval hours" /></FormField>
              <FormField label="Retain rule" constraintText="Number of snapshots/AMIs to keep per resource."><Input type="number" value={retain} onChange={({ detail }) => setRetain(detail.value)} ariaLabel="Retain count" /></FormField>
            </SpaceBetween>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
