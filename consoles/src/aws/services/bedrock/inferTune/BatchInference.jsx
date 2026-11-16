/* Batch inference: asynchronous jobs over S3 JSONL, answered by the local-LLM seam (max 25 records per job). */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Button from "@cloudscape-design/components/button";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import * as api from "./api.js";
import { CreateModal, Field, HowItWorks, ModelSelect, Page, jobStatus, providerOf, useModelOptions, when } from "./Shared.jsx";

export default function BatchInference() {
  const notify = useNotify();
  const t = useAsync(() => api.listBatchJobs(), []);
  const models = useModelOptions();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(""), [model, setModel] = useState(null), [inp, setInp] = useState("s3://"), [out, setOut] = useState("s3://");
  const create = <Button variant="primary" onClick={() => setOpen(true)}>Create job</Button>;
  return (
    <Page title="Batch inference" description="Run model inferences asynchronously in batches to efficiently process many requests at once. Batch inference speeds up inferences on large datasets. The job will output a JSON file in the assigned S3 location.">
      <HowItWorks steps={[
        { title: "Create a batch inference job", body: "To create a batch inference job, prepare your input data to match the required format and select the model." },
        { title: "Use the results", body: "Use the batch inference results stored in the output S3 bucket for your workflow or application." },
      ]} />
      <ResourceTable variant="container" resourceName="Batch inference jobs" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="jobArn"
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find batch inference jobs"
        actions={<><Button disabled={!sel.length || sel[0].status !== "InProgress"} onClick={async () => { await api.stopBatchJob(sel[0].jobArn); t.reload(); }}>Stop job</Button>{create}</>}
        empty={{ title: "No batch inference models", action: create }}
        columns={[
          { id: "name", header: "Job name", isRowHeader: true, sortingField: "jobName", cell: (j) => j.jobName },
          { id: "status", header: "Status", sortingField: "status", cell: (j) => jobStatus(j.status) },
          { id: "model", header: "Model", cell: (j) => j.modelId },
          { id: "prov", header: "Provider", cell: (j) => providerOf(j.modelId) },
          { id: "type", header: "Invocation type", cell: () => "InvokeModel" },
          { id: "output", header: "Output", cell: (j) => j.outputDataConfig?.s3OutputDataConfig?.s3Uri },
          { id: "created", header: "Creation time (UTC)", sortingField: "submitTime", cell: (j) => when(j.submitTime) },
        ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Create batch inference job" disabled={!name || !model || inp.length < 6 || out.length < 6}
        onSubmit={async () => { await api.createBatchJob(name, model, inp, out); notify.success(`Batch inference job "${name}" submitted.`); t.reload(); }}>
        <Alert type="info">Jobs run on the local model over a JSONL file (one {"{recordId, modelInput}"} per line); at most 25 records are processed per job. Results are written to the output S3 location.</Alert>
        <Field label="Job name" value={name} onChange={setName} />
        <ModelSelect value={model} onChange={setModel} {...models} />
        <Field label="Input data (S3 location)" placeholder="s3://my-bucket/input/" value={inp} onChange={setInp} />
        <Field label="Output data (S3 location)" placeholder="s3://my-bucket/output/" value={out} onChange={setOut} />
      </CreateModal>
    </Page>
  );
}
