/* Custom models (Models / Jobs tabs). A job on a TRAINABLE base (the embedding model or vyomi.head.*) really trains a small head and links to a detail page;
 * on any other base model it stays METADATA ONLY: it completes with a custom-model record, nothing is trained. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { navigate } from "../../../../common/router.js";
import { HONEST, KEEP_TAB_OPEN, NON_TRAINABLE, TASKS, TRAINABLE_BASES, isNano, isTrainableBase } from "../../../../common/training.js";
import TrainingData from "./TrainingData.jsx";
import * as api from "./api.js";
import { CreateModal, Field, HowItWorks, ModelSelect, Page, jobStatus, modelOf, useModelOptions, when } from "./Shared.jsx";

export default function CustomModels() {
  const notify = useNotify();
  const models = useAsync(() => api.listCustomModels(), []);
  const jobs = useAsync(() => api.listCustomizationJobs(), []);
  const base = useModelOptions();
  const [banner, setBanner] = useState(true);
  const [sel, setSel] = useState([]), [jsel, setJsel] = useState([]);
  const [open, setOpen] = useState(false), [del, setDel] = useState(false);
  const [jn, setJn] = useState(""), [cn, setCn] = useState(""), [bm, setBm] = useState(null), [tr, setTr] = useState("s3://"), [ou, setOu] = useState("s3://"), [ep, setEp] = useState("1");
  const [task, setTask] = useState("classifier"), [chk, setChk] = useState(null);
  const trainable = isTrainableBase(bm);
  const baseOptions = [{ label: "Trainable in this simulator", options: TRAINABLE_BASES.map((b) => ({ label: b.name, value: b.id, description: "Real training of a small head" })) }, { label: "Foundation models (metadata only)", options: base.options }];
  const reloadAll = () => { models.reload(); jobs.reload(); };
  const create = <Button variant="primary" onClick={() => setOpen(true)}>Create fine-tuning job</Button>;
  const none = { title: "No custom models", subtitle: "There are currently no resources.", action: create };
  return (
    <Page title="Custom models" description="Customize models using available customization processes. Access and manage custom models based on your region's capabilities.">
      {banner && <Alert type="info" dismissible onDismiss={() => setBanner(false)} action={<Button>Learn more</Button>}>Starting October 7th, 2025, you will no longer be able to access Continued pre-training in Bedrock. You can continue to use continued pre-training for Amazon Nova models on Amazon SageMaker.</Alert>}
      <HowItWorks steps={[
        { title: "Create a model", body: "Select a model(s) to customize using training and validation (if applicable) datasets in an Amazon S3 bucket. Share your custom model with other accounts if you have an AWS Organizations account. You can copy a model that you own or that has been shared with you to another AWS Region." },
        { title: "Purchase provisioned throughput to use the custom model", body: "Purchase provisioned throughput to use a custom fine-tuned model, a continued pre-trained model or a copied model. You can then use your model in the Amazon Bedrock playgrounds or in your applications." },
      ]} />
      <Tabs tabs={[
        { id: "models", label: "Models", content: (
          <SpaceBetween size="l">
            <ResourceTable variant="container" resourceName="Models" description="Customized model and their jobs successfully completed will appear here." items={models.data || []} loading={models.loading} error={models.error} onRefresh={models.reload}
              trackBy="modelArn" selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find model" empty={none}
              actions={<><ButtonDropdown disabled={!sel.length} items={[{ id: "pt", text: "Provisioned Throughput" }, { id: "playground", text: "Open in playground" }]} onItemClick={({ detail }) => navigate("bedrock", detail.id === "pt" ? "provisioned-throughput" : "playground")}>Setup inference</ButtonDropdown>{create}<ButtonDropdown disabled={!sel.length} items={[{ id: "pt", text: "Purchase provisioned throughput" }, { id: "delete", text: "Delete" }]}
                onItemClick={({ detail }) => (detail.id === "delete" ? setDel(true) : navigate("bedrock", "provisioned-throughput"))}>Actions</ButtonDropdown></>}
              columns={[
                { id: "name", header: "Custom model name", isRowHeader: true, sortingField: "modelName", cell: (m) => m.modelName },
                { id: "status", header: "Model Status", cell: (m) => jobStatus(m.modelStatus) },
                { id: "base", header: "Customized model", cell: (m) => m.baseModelName },
                { id: "type", header: "Type", cell: (m) => ({ FINE_TUNING: "Fine-tuning", CONTINUED_PRE_TRAINING: "Continued pre-training", DISTILLATION: "Distillation" })[m.customizationType] || m.customizationType },
                { id: "share", header: "Share status", cell: () => "Not shared" },
                { id: "created", header: "Creation time (UTC)", sortingField: "creationTime", cell: (m) => when(m.creationTime) },
              ]} />
            <Table variant="container" items={[]} trackBy="modelArn" header={<Header variant="h2" counter="(0)" description="A list of models that have been shared with you by another account. To make use of a model that has been shared with you, copy it into a region and then purchase provisioned throughput for it." actions={<Button disabled>Copy</Button>}>Models shared with you</Header>}
              columnDefinitions={["Shared model name", "Model Status", "Model ARN", "Type", "Owner ID", "Last updated"].map((h) => ({ id: h, header: h, cell: () => "" }))}
              empty={<Box textAlign="center"><b>No model</b><Box variant="p">No custom models have been shared with you by other accounts.</Box></Box>} />
          </SpaceBetween>) },
        { id: "jobs", label: "Jobs", content:
          <ResourceTable variant="container" resourceName="Jobs" description="Jobs are initiated when you begin customizing or copying a model." items={jobs.data || []} loading={jobs.loading} error={jobs.error} onRefresh={jobs.reload}
            trackBy="jobArn" selectionType="single" selectedItems={jsel} onSelectionChange={setJsel} filterPlaceholder="Find jobs"
            actions={<><Button disabled={!jsel.length || jsel[0].status !== "InProgress"} onClick={async () => { await api.stopCustomizationJob(jsel[0].jobArn); jobs.reload(); }}>Stop job</Button>{create}</>}
            empty={{ title: "No active jobs", subtitle: "There are currently no resources." }}
            columns={[
              { id: "name", header: "Job name", isRowHeader: true, sortingField: "jobName", cell: (j) => (isTrainableBase(j.baseModelArn) ? <Link href={`#/bedrock/custom-models/jobs/${encodeURIComponent(String(j.jobArn).split("/").pop())}`}>{j.jobName}</Link> : j.jobName) },
              { id: "status", header: "Status", cell: (j) => jobStatus(j.status) },
              { id: "source", header: "Source", cell: (j) => modelOf(j.baseModelArn) },
              { id: "type", header: "Job type", cell: (j) => (j.customizationType === "FINE_TUNING" ? "Fine-tuning" : j.customizationType) },
              { id: "cm", header: "Custom model name", cell: (j) => j.customModelName },
              { id: "created", header: "Creation time (UTC)", sortingField: "creationTime", cell: (j) => when(j.creationTime) },
            ]} /> },
      ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Create fine-tuning job" disabled={!jn || !cn || !bm || tr.length < 6 || ou.length < 6 || (trainable && !chk?.ok)}
        onSubmit={async () => { const r = await api.createCustomizationJob(jn, cn, bm, tr, ou, ep, trainable ? task : undefined); notify.success(`Fine-tuning job "${jn}" started.`); if (trainable) { navigate("bedrock", "custom-models", "jobs", String(r.jobArn || jn).split("/").pop()); return; } setTimeout(reloadAll, 2600); reloadAll(); }}>
        {trainable
          ? <Alert type="info" data-testid="create-honest">{HONEST}{isNano() ? ` ${KEEP_TAB_OPEN}` : ""}</Alert>
          : <Alert type="warning" data-testid="create-meta-only">{bm ? NON_TRAINABLE : "Choose a base model."} The job completes after a moment and registers the custom model so the lifecycle (job, model, provisioned throughput) can be exercised through the SDK and console.</Alert>}
        <Field label="Job name" value={jn} onChange={setJn} />
        <Field label="Custom model name" value={cn} onChange={setCn} />
        <ModelSelect ariaLabel="Base model" value={bm} onChange={(v) => { setBm(v); if (isTrainableBase(v)) setEp("8"); }} options={baseOptions} loading={base.loading} />
        {trainable ? (<>
          <FormField label="Task type" description={TASKS.find((x) => x.id === task)?.help}>
            <Select selectedOption={{ label: TASKS.find((x) => x.id === task).label, value: task }} options={TASKS.map((x) => ({ label: x.label, value: x.id }))} ariaLabel="Task type" onChange={({ detail }) => setTask(detail.selectedOption.value)} />
          </FormField>
          <TrainingData taskType={task} uri={tr} onUri={setTr} onCheck={setChk} />
        </>) : <Field label="Training data (S3 location)" value={tr} onChange={setTr} />}
        <Field label="Output data (S3 location)" value={ou} onChange={setOu} />
        <Field label="Epochs" type="number" value={ep} onChange={setEp} />
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="custom model" names={sel.map((m) => m.modelName)} onConfirm={async () => { await api.deleteCustomModel(sel[0].modelArn); setSel([]); models.reload(); }} />
    </Page>
  );
}
