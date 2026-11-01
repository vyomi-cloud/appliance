/* AWS Verified Access: instances/trust providers/groups/endpoints are real objects with a real
 * policy EVALUATOR (VerifyAccessEndpointPolicy mirrors the actual AWS console's "Test policy"
 * tool). Federating to a real external IdP/device-trust provider needs a real third party and
 * is not simulated — see aws.vpc.verified-access's limitations. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function SimpleCreateModal({ header, fields, onDismiss, onCreated, create, notify, successText }) {
  const [values, setValues] = useState(Object.fromEntries(fields.map((f) => [f.key, f.default || ""])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { const r = await create(values); notify.success(successText(r)); onCreated(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  const required = fields.filter((f) => f.required).every((f) => values[f.key]);
  return (
    <Modal visible onDismiss={onDismiss} size="large" header={header} footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
      <Button formAction="none" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!required} onClick={submit}>Create</Button>
    </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          {fields.map((f) => (
            <FormField key={f.key} label={f.label} description={f.description}>
              {f.options ? (
                <Select selectedOption={values[f.key] ? { value: values[f.key], label: values[f.key] } : null} placeholder={f.placeholder}
                  options={f.options.map((o) => ({ value: o, label: o }))} onChange={({ detail }) => setValues((v) => ({ ...v, [f.key]: detail.selectedOption.value }))} />
              ) : f.multiline ? (
                <Textarea value={values[f.key]} placeholder={f.placeholder} rows={6} onChange={({ detail }) => setValues((v) => ({ ...v, [f.key]: detail.value }))} />
              ) : (
                <Input value={values[f.key]} placeholder={f.placeholder} onChange={({ detail }) => setValues((v) => ({ ...v, [f.key]: detail.value }))} />
              )}
            </FormField>
          ))}
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

function ResourceList({ title, capabilityId, resourceName, trackBy, list, del, columns, createLabel, deleteLabel, CreateForm, extra }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [showDel, setShowDel] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const t = useAsync(list, []);
  const rows = t.data || [];
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      <CapabilityContainer id={capabilityId} title={title} counter={`(${rows.length})`}>
        <SpaceBetween size="l">
          <ResourceTable resourceName={resourceName} items={rows} loading={t.loading} error={t.error} onRefresh={t.reload}
            trackBy={trackBy} selectionType="multi" selectedItems={sel} onSelectionChange={setSel} columns={columns}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: deleteLabel }]} onItemClick={() => setShowDel(true)}>Actions</ButtonDropdown>
                <Button variant="primary" onClick={() => setShowCreate(true)}>{createLabel}</Button>
              </SpaceBetween>
            } />
          {extra && extra(rows, t.reload)}
        </SpaceBetween>
      </CapabilityContainer>
      <DeleteModal visible={showDel} resourceType={resourceName.toLowerCase()} names={sel.map((r) => r[trackBy])} confirmText="delete" onDismiss={() => setShowDel(false)}
        onConfirm={async () => { for (const r of sel) await del(r[trackBy]); notify.success(`${sel.length} deleted.`); setSel([]); t.reload(); }} />
      {showCreate && <CreateForm onDismiss={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); t.reload(); }} create={undefined} notify={notify} />}
    </ContentLayout>
  );
}

export function VerifiedAccessInstances() {
  return (
    <ResourceList title="Verified Access instances" capabilityId="aws.vpc.verified-access" resourceName="Verified Access instances" trackBy="VerifiedAccessInstanceId"
      list={() => api.describeVerifiedAccessInstances()} del={api.deleteVerifiedAccessInstance}
      createLabel="Create Verified Access instance" deleteLabel="Delete instance"
      columns={[
        { id: "id", header: "Verified Access instance ID", isRowHeader: true, cell: (i) => i.VerifiedAccessInstanceId },
        { id: "desc", header: "Description", cell: (i) => i.Description || "-" },
        { id: "tp", header: "Trust providers", cell: (i) => i.TrustProviderIds?.length || 0 },
        { id: "created", header: "Created", cell: (i) => i.CreationTime },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create Verified Access instance" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[{ key: "description", label: "Description", placeholder: "my-verified-access-instance" }]}
          create={(v) => api.createVerifiedAccessInstance(v.description)} successText={(i) => `Instance "${i.VerifiedAccessInstanceId}" created.`} />
      )}
    />
  );
}

export function VerifiedAccessTrustProviders() {
  return (
    <ResourceList title="Verified Access trust providers" capabilityId="aws.vpc.verified-access" resourceName="Verified Access trust providers" trackBy="VerifiedAccessTrustProviderId"
      list={() => api.describeVerifiedAccessTrustProviders()} del={api.deleteVerifiedAccessTrustProvider}
      createLabel="Create Verified Access trust provider" deleteLabel="Delete trust provider"
      columns={[
        { id: "id", header: "Trust provider ID", isRowHeader: true, cell: (t) => t.VerifiedAccessTrustProviderId },
        { id: "type", header: "Trust provider type", cell: (t) => t.TrustProviderType },
        { id: "desc", header: "Description", cell: (t) => t.Description || "-" },
        { id: "created", header: "Created", cell: (t) => t.CreationTime },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create Verified Access trust provider" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[
            { key: "type", label: "Trust provider type", required: true, options: ["user", "device"], placeholder: "Select a type",
              description: "Federating to a real external IdP (user) or device-trust provider is not simulated — Vyomi records the declared type and evaluates policies against test context." },
            { key: "name", label: "Policy reference name", required: true, placeholder: "idp" },
            { key: "description", label: "Description", placeholder: "my-trust-provider" },
          ]}
          create={(v) => api.createVerifiedAccessTrustProvider(v.type, v.name, v.description)} successText={(t) => `Trust provider "${t.VerifiedAccessTrustProviderId}" created.`} />
      )}
    />
  );
}

export function VerifiedAccessGroups() {
  const instances = useAsync(() => api.describeVerifiedAccessInstances(), []);
  return (
    <ResourceList title="Verified Access groups" capabilityId="aws.vpc.verified-access" resourceName="Verified Access groups" trackBy="VerifiedAccessGroupId"
      list={() => api.describeVerifiedAccessGroups()} del={api.deleteVerifiedAccessGroup}
      createLabel="Create Verified Access group" deleteLabel="Delete group"
      columns={[
        { id: "id", header: "Group ID", isRowHeader: true, cell: (g) => g.VerifiedAccessGroupId },
        { id: "inst", header: "Instance ID", cell: (g) => g.VerifiedAccessInstanceId },
        { id: "desc", header: "Description", cell: (g) => g.Description || "-" },
        { id: "created", header: "Created", cell: (g) => g.CreationTime },
      ]}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create Verified Access group" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[
            { key: "instanceId", label: "Verified Access instance", required: true, options: (instances.data || []).map((i) => i.VerifiedAccessInstanceId), placeholder: "Select an instance" },
            { key: "description", label: "Description", placeholder: "my-group" },
            { key: "policy", label: "Policy document", multiline: true, placeholder: 'permit(context.device.trust == "high");' },
          ]}
          create={(v) => api.createVerifiedAccessGroup(v.instanceId, v.description, v.policy)} successText={(g) => `Group "${g.VerifiedAccessGroupId}" created.`} />
      )}
    />
  );
}

function PolicyTester({ endpointId }) {
  const [context, setContext] = useState('{\n  "device": { "trust": "high" }\n}');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setResult(await api.verifyAccessEndpointPolicy(endpointId, JSON.parse(context))); }
    catch (e) { setResult({ error: String(e) }); } finally { setBusy(false); }
  };
  return (
    <Box padding={{ top: "s" }}>
      <SpaceBetween size="s">
        <FormField label="Test policy — identity/device context" description="Real policy evaluation (no external IdP needed): Vyomi runs the endpoint's policy document against this context, same as the AWS console's Test policy tool.">
          <Textarea value={context} rows={4} onChange={({ detail }) => setContext(detail.value)} />
        </FormField>
        <Button loading={busy} onClick={run}>Run test</Button>
        {result && (result.error ? <Box color="text-status-error">{result.error}</Box> : (
          <Box>Result: <b>{result.Allowed ? "Allowed" : "Denied"}</b> — {result.Statements?.[0]}</Box>
        ))}
      </SpaceBetween>
    </Box>
  );
}

export function VerifiedAccessEndpoints() {
  const groups = useAsync(() => api.describeVerifiedAccessGroups(), []);
  const [tested, setTested] = useState(null);
  return (
    <ResourceList title="Verified Access endpoints" capabilityId="aws.vpc.verified-access" resourceName="Verified Access endpoints" trackBy="VerifiedAccessEndpointId"
      list={() => api.describeVerifiedAccessEndpoints()} del={api.deleteVerifiedAccessEndpoint}
      createLabel="Create Verified Access endpoint" deleteLabel="Delete endpoint"
      columns={[
        { id: "id", header: "Endpoint ID", isRowHeader: true, cell: (e) => e.VerifiedAccessEndpointId },
        { id: "domain", header: "Application domain", cell: (e) => e.ApplicationDomain },
        { id: "endpointDomain", header: "Endpoint domain", cell: (e) => e.EndpointDomain },
        { id: "type", header: "Type", cell: (e) => e.EndpointType },
        { id: "status", header: "Status", cell: (e) => e.Status },
        { id: "test", header: "Policy", cell: (e) => <Button variant="inline-link" onClick={() => setTested(tested === e.VerifiedAccessEndpointId ? null : e.VerifiedAccessEndpointId)}>{tested === e.VerifiedAccessEndpointId ? "Hide tester" : "Test policy"}</Button> },
      ]}
      extra={() => tested && <PolicyTester endpointId={tested} />}
      CreateForm={({ onDismiss, onCreated, notify }) => (
        <SimpleCreateModal header="Create Verified Access endpoint" onDismiss={onDismiss} onCreated={onCreated} notify={notify}
          fields={[
            { key: "groupId", label: "Verified Access group", required: true, options: (groups.data || []).map((g) => g.VerifiedAccessGroupId), placeholder: "Select a group" },
            { key: "domain", label: "Application domain", required: true, placeholder: "app.example.internal" },
            { key: "policy", label: "Policy document — optional (overrides the group's)", multiline: true, placeholder: 'permit(context.device.trust == "high");' },
          ]}
          create={(v) => api.createVerifiedAccessEndpoint(v.groupId, v.domain, "network-interface", v.policy)} successText={(e) => `Endpoint "${e.VerifiedAccessEndpointId}" created.`} />
      )}
    />
  );
}
