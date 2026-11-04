/* Hooks — registered through the registry (Type=HOOK: RegisterType/SetTypeConfiguration/
 * DeregisterType/ListTypes/DescribeType) and really enforced on every CreateStack/
 * UpdateStack/DeleteStack the hook targets (core/cloudformation_core.py: _run_hooks).
 * A hook's policy is a single built-in check — the required tag keys configured on it —
 * not arbitrary custom handler code (core/capabilities/aws/cloudformation.json:
 * aws.cloudformation.hooks). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Multiselect from "@cloudscape-design/components/multiselect";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const OP_OPTIONS = [
  { value: "CREATE", label: "Create stack" },
  { value: "UPDATE", label: "Update stack" },
  { value: "DELETE", label: "Delete stack" },
];

function targetsText(h) {
  const ops = h.TargetOperations.length ? h.TargetOperations.join(", ") : "none";
  const scope = h.TargetStacks === "ALL" ? "All stacks" : (h.TargetStacks.join(", ") || "none");
  return `${ops} · ${scope}`;
}

function CreateHookModal({ visible, onDismiss, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [failureMode, setFailureMode] = useState("FAIL");
  const [ops, setOps] = useState([OP_OPTIONS[0], OP_OPTIONS[1]]);
  const [scope, setScope] = useState("ALL");
  const [stackNames, setStackNames] = useState("");
  const [requiredTags, setRequiredTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const close = () => {
    setName(""); setDescription(""); setFailureMode("FAIL"); setOps([OP_OPTIONS[0], OP_OPTIONS[1]]);
    setScope("ALL"); setStackNames(""); setRequiredTags(""); setError(null);
    onDismiss();
  };
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createHook({
        typeName: name,
        description,
        failureMode,
        targetOperations: ops.map((o) => o.value),
        targetStacks: scope === "ALL" ? "ALL" : stackNames.split(",").map((s) => s.trim()).filter(Boolean),
        requiredTagKeys: requiredTags.split(",").map((s) => s.trim()).filter(Boolean),
      });
      notify.success(`Hook "${name}" created.`);
      close(); onCreated();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const valid = name.includes("::") && ops.length > 0 && (scope === "ALL" || stackNames.trim());

  return (
    <Modal visible={visible} onDismiss={close} size="large" header="Create a Hook"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={close}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!valid} onClick={submit}>Create hook</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Hook name" description="Organization::Service::HookName">
          <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="MyOrg::Policy::RequireOwnerTag" ariaLabel="Hook name" />
        </FormField>
        <FormField label="Description — optional">
          <Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
        </FormField>
        <FormField label="Failure mode" description="Fail stops the stack operation when the hook fails; Warn lets it continue and only records the failure.">
          <RadioGroup value={failureMode} onChange={({ detail }) => setFailureMode(detail.value)} items={[
            { value: "FAIL", label: "Fail" }, { value: "WARN", label: "Warn" },
          ]} />
        </FormField>
        <FormField label="Target operations">
          <Multiselect selectedOptions={ops} onChange={({ detail }) => setOps(detail.selectedOptions)} options={OP_OPTIONS} placeholder="Choose operations" ariaLabel="Target operations" />
        </FormField>
        <FormField label="Target stacks">
          <RadioGroup value={scope} onChange={({ detail }) => setScope(detail.value)} items={[
            { value: "ALL", label: "All stacks" }, { value: "SPECIFIC", label: "Specific stacks" },
          ]} />
        </FormField>
        {scope === "SPECIFIC" && (
          <FormField label="Stack names" description="Comma-separated.">
            <Input value={stackNames} onChange={({ detail }) => setStackNames(detail.value)} ariaLabel="Stack names" />
          </FormField>
        )}
        <FormField label="Required tag keys" description="Comma-separated. The hook fails any targeted stack missing one of these tag keys.">
          <Input value={requiredTags} onChange={({ detail }) => setRequiredTags(detail.value)} placeholder="Owner, CostCenter" ariaLabel="Required tag keys" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function Hooks() {
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listHooks(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);

  const toggleEnabled = async () => {
    const h = sel[0];
    try {
      await api.setHookEnabled(h, !h.Enabled);
      notify.success(`Hook "${h.TypeName}" ${h.Enabled ? "disabled" : "enabled"}.`);
      setSel([]); reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Hooks</Header>}>
      <SpaceBetween size="l">
        <ResourceTable
          resourceName="Hooks"
          items={data}
          trackBy="TypeName"
          loading={loading}
          error={error}
          onRefresh={reload}
          selectionType="single"
          selectedItems={sel}
          onSelectionChange={setSel}
          filterPlaceholder="Find hooks"
          columns={[
            { id: "n", header: "Name", isRowHeader: true, cell: (h) => h.TypeName },
            { id: "t", header: "Type", cell: () => "Private hook" },
            { id: "m", header: "Mode", cell: (h) => (h.FailureMode === "FAIL" ? "Fail" : "Warn") },
            { id: "tg", header: "Targets", cell: (h) => targetsText(h) },
            { id: "s", header: "Hook status", cell: (h) => <StatusIndicator type={h.Enabled ? "success" : "stopped"}>{h.Enabled ? "Enabled" : "Disabled"}</StatusIndicator> },
            { id: "u", header: "Last updated", cell: (h) => fmtDate(h.LastUpdated) },
            { id: "d", header: "Description", cell: (h) => h.Description || "-" },
          ]}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <ButtonDropdown disabled={sel.length !== 1} onItemClick={({ detail }) => { if (detail.id === "toggle") toggleEnabled(); }}
                items={[{ id: "toggle", text: sel[0]?.Enabled ? "Disable" : "Enable" }]}>Actions</ButtonDropdown>
              <Button disabled={sel.length !== 1} onClick={() => setDel(true)}>Delete</Button>
              <Button variant="primary" onClick={() => setCreate(true)}>Create a Hook</Button>
            </SpaceBetween>
          }
          empty={{ title: "No hooks", subtitle: "Create a hook to enforce a required-tag policy on stack operations.", action: <Button onClick={() => setCreate(true)}>Create a Hook</Button> }}
        />
        <Container header={<Header variant="h2">How it works</Header>}>
          <Box variant="p">
            A hook runs right before CloudFormation creates, updates or deletes any stack it targets
            and checks the tag keys you require. A stack missing one fails the invocation: a Fail-mode
            hook stops the operation, a Warn-mode hook lets it continue and only records the failure.
            See the invocation history on the Invocation summary page.
          </Box>
        </Container>
      </SpaceBetween>
      <CreateHookModal visible={create} onDismiss={() => setCreate(false)} onCreated={reload} />
      <DeleteModal
        visible={del}
        resourceType="hook"
        names={sel.map((h) => h.TypeName)}
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          await api.deleteHook(sel[0].TypeName);
          notify.success(`Hook "${sel[0].TypeName}" deleted.`);
          setSel([]); reload();
        }}
      />
    </ContentLayout>
  );
}
