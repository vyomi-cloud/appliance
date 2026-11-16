/* Provisioned Throughput: metadata only (InService at once; no capacity is reserved or billed). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import FormField from "@cloudscape-design/components/form-field";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import * as api from "./api.js";
import { CreateModal, Field, ModelSelect, Page, jobStatus, modelOf, useModelOptions, when } from "./Shared.jsx";

const TERMS = [{ label: "No commitment", value: "" }, { label: "1 month", value: "OneMonth" }, { label: "6 months", value: "SixMonths" }];
const termText = (d) => ({ OneMonth: "1 month", SixMonths: "6 months" })[d] || "No commitment";
const Stat = ({ label, value }) => <div><Box variant="awsui-key-label">{label}</Box><Box variant="awsui-value-large">{value}</Box></div>;

export default function ProvisionedThroughput() {
  const notify = useNotify();
  const t = useAsync(() => api.listProvisioned(), []);
  const custom = useAsync(() => api.listCustomModels(), []);
  const models = useModelOptions();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false), [del, setDel] = useState(false);
  const [name, setName] = useState(""), [model, setModel] = useState(null), [units, setUnits] = useState("1"), [term, setTerm] = useState(TERMS[0]);
  const items = t.data || [];
  const count = (s) => items.filter((x) => x.status === s).length;
  const options = [...models.options, ...(custom.data || []).map((c) => ({ label: c.modelName, value: c.modelArn, description: "Custom model", tags: ["Custom"] }))];
  const buy = <Button variant="primary" onClick={() => setOpen(true)}>Purchase Provisioned Throughput</Button>;
  return (
    <Page title="Provisioned Throughput" description="Provisioned Throughput allows you to have dedicated capacity to deploy your models.">
      <Container header={<Header variant="h2">Overview</Header>}>
        <ColumnLayout columns={4} variant="text-grid">
          <Stat label="Active" value={count("InService")} /><Stat label="Failed" value={count("Failed")} /><Stat label="Updating" value={count("Updating")} /><Stat label="Inactive" value={items.length - count("InService") - count("Failed") - count("Updating")} />
        </ColumnLayout>
      </Container>
      <ResourceTable variant="container" resourceName="Provisioned Throughput" items={items} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="provisionedModelArn"
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find provisioned throughput"
        actions={<><ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>{buy}</>}
        empty={{ title: "No Provisioned Throughput", subtitle: "There are currently no resources.", action: buy }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "provisionedModelName", cell: (x) => x.provisionedModelName },
          { id: "status", header: "Status", sortingField: "status", cell: (x) => jobStatus(x.status === "InService" ? "Active" : x.status) },
          { id: "model", header: "Model", cell: (x) => modelOf(x.modelArn) },
          { id: "units", header: "Model units", sortingField: "modelUnits", cell: (x) => x.modelUnits },
          { id: "term", header: "Commitment term", cell: (x) => termText(x.commitmentDuration) },
          { id: "created", header: "Creation time (UTC)", sortingField: "creationTime", cell: (x) => when(x.creationTime) },
          { id: "end", header: "End time", cell: (x) => when(x.commitmentExpirationTime) },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Purchase Provisioned Throughput" submitLabel="Purchase" disabled={!name || !model || !(Number(units) >= 1)}
        onSubmit={async () => { await api.createProvisioned(name, model, units, term.value); notify.success(`Provisioned Throughput "${name}" purchased (metadata only, nothing is billed).`); setName(""); t.reload(); }}>
        <Field label="Provisioned Throughput name" value={name} onChange={setName} />
        <FormField label="Select model"><ModelSelect value={model} onChange={setModel} options={options} loading={models.loading} /></FormField>
        <FormField label="Commitment term"><Select selectedOption={term} options={TERMS} onChange={({ detail }) => setTerm(detail.selectedOption)} ariaLabel="Commitment term" /></FormField>
        <Field label="Model units" type="number" value={units} onChange={setUnits} />
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="Provisioned Throughput" names={sel.map((x) => x.provisionedModelName)}
        onConfirm={async () => { await api.deleteProvisioned(sel[0].provisionedModelArn); setSel([]); t.reload(); }} />
    </Page>
  );
}
