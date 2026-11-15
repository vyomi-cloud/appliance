/* Inference profiles (real console: System-defined / Application tabs). Backed by ListInferenceProfiles/CreateInferenceProfile. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import CopyToClipboard from "@cloudscape-design/components/copy-to-clipboard";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import KeyValuePairs from "@cloudscape-design/components/key-value-pairs";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import * as api from "./api.js";
import { CreateModal, Field, HowItWorks, ModelSelect, Page, regionName, regionOf, useModelOptions, when, jobStatus, modelOf } from "./Shared.jsx";

const copy = (t, label) => <CopyToClipboard variant="inline" textToCopy={t} visibleContent={<span style={{ display: "inline-block", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", verticalAlign: "bottom" }}>{t}</span>} copySuccessText={`${label} copied`} copyErrorText="Copy failed" />;
const regions = (p) => [...new Set((p.models || []).map((m) => regionOf(m.modelArn)).filter(Boolean))];
const modelName = (p) => p.inferenceProfileName.replace(/^(US|EU|APAC) (Amazon|Anthropic|Meta|Cohere) /, "");

function Detail({ p, onDismiss }) {
  return (
    <Modal visible={!!p} onDismiss={onDismiss} header={p?.inferenceProfileName} size="large" footer={<Box float="right"><Button onClick={onDismiss}>Close</Button></Box>}>
      {p && <KeyValuePairs columns={2} items={[
        { label: "Inference profile ID", value: p.inferenceProfileId }, { label: "Type", value: p.type },
        { label: "Status", value: jobStatus(p.status) }, { label: "Description", value: p.description || "-" },
        { label: "Inference profile ARN", value: p.inferenceProfileArn }, { label: "Created", value: when(p.createdAt) },
        { label: "Regions routed to", value: regions(p).map(regionName).join(", ") || "-" },
        { label: "Model ARNs", value: <Box>{(p.models || []).map((m) => <div key={m.modelArn}>{m.modelArn}</div>)}</Box> },
      ]} />}
    </Modal>
  );
}

export default function InferenceProfiles() {
  const notify = useNotify();
  const sys = useAsync(() => api.listProfiles("SYSTEM_DEFINED"), []);
  const app = useAsync(() => api.listProfiles("APPLICATION"), []);
  const models = useModelOptions();
  const [detail, setDetail] = useState(null);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [sel, setSel] = useState([]);
  const [name, setName] = useState(""), [desc, setDesc] = useState(""), [src, setSrc] = useState(null);
  const srcOptions = (sys.data || []).map((p) => ({ label: p.inferenceProfileName, value: p.inferenceProfileArn, description: p.inferenceProfileId }));
  const link = (txt, p) => <Link onFollow={(e) => { e.preventDefault(); setDetail(p); }}>{txt}</Link>;
  return (
    <Page title="Inference profiles" description="An inference profile defines a model and the Regions to which it can route inference requests. You can use inference profiles to track costs and metrics for inference requests made to the Regions in it. Inference profiles also increase throughput and improve resiliency by routing your requests across multiple AWS Regions during peak utilization bursts.">
      <HowItWorks steps={[
        { title: "Select a system-defined inference profile", body: "Select a system-defined inference profile from the table to view information about the model and Regions to which it can route inference requests." },
        { title: "Use a system-defined inference profile", body: "You can do cross-region inference by specifying a system-defined inference profile ID or its ARN when running model inference or using an Amazon Bedrock resource. You can also create a application inference profile from the system-defined one to track costs and usage." },
      ]} />
      <Tabs tabs={[
        { id: "system", label: "System-defined", content:
          <ResourceTable variant="container" resourceName="System-defined inference profiles" items={sys.data || []} loading={sys.loading} error={sys.error} onRefresh={sys.reload} trackBy="inferenceProfileId" filterPlaceholder="Find inference profiles"
            columns={[
              { id: "name", header: "Name", isRowHeader: true, sortingField: "inferenceProfileName", cell: (p) => link(p.inferenceProfileName, p) },
              { id: "model", header: "Model", cell: (p) => link(modelName(p), p) },
              { id: "desc", header: "Description", cell: (p) => <span title={p.description}>{(p.description || "").slice(0, 28)}...</span> },
              { id: "id", header: "Inference profile ID", sortingField: "inferenceProfileId", cell: (p) => copy(p.inferenceProfileId, "ID") },
              { id: "arn", header: "Inference profile ARN", cell: (p) => copy(p.inferenceProfileArn, "ARN") },
              { id: "regions", header: "AWS Regions", cell: (p) => regions(p).map((r) => <div key={r}>{regionName(r)}</div>) },
            ]} /> },
        { id: "application", label: "Application", content:
          <ResourceTable variant="container" resourceName="Application inference profiles" items={app.data || []} loading={app.loading} error={app.error} onRefresh={app.reload} trackBy="inferenceProfileId"
            selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find inference profiles"
            actions={<><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button><Button variant="primary" onClick={() => setCreate(true)}>Create inference profile</Button></>}
            empty={{ title: "No base models", subtitle: "There are currently no resources." }}
            columns={[
              { id: "name", header: "Name", isRowHeader: true, sortingField: "inferenceProfileName", cell: (p) => link(p.inferenceProfileName, p) },
              { id: "model", header: "Model", cell: (p) => modelOf((p.models || [])[0]?.modelArn) },
              { id: "status", header: "Status", cell: (p) => jobStatus(p.status) },
              { id: "desc", header: "Description", cell: (p) => p.description || "-" },
              { id: "id", header: "Inference profile ID", cell: (p) => copy(p.inferenceProfileId, "ID") },
              { id: "arn", header: "Inference profile ARN", cell: (p) => copy(p.inferenceProfileArn, "ARN") },
              { id: "regions", header: "AWS Regions", cell: (p) => regions(p).map(regionName).join(", ") },
              { id: "created", header: "Creation time", sortingField: "createdAt", cell: (p) => when(p.createdAt) },
              { id: "updated", header: "Last updated", cell: (p) => when(p.updatedAt) },
            ]} /> },
      ]} />
      <Detail p={detail} onDismiss={() => setDetail(null)} />
      <CreateModal visible={create} onDismiss={() => setCreate(false)} header="Create inference profile" disabled={!name || !src}
        onSubmit={async () => { await api.createProfile(name, desc, src); notify.success(`Application inference profile "${name}" created.`); setName(""); setDesc(""); setSrc(null); app.reload(); }}>
        <Field label="Inference profile name" constraint="Letters, numbers, spaces, hyphens and underscores" value={name} onChange={setName} />
        <Field label="Description - optional" value={desc} onChange={setDesc} />
        <ModelSelect ariaLabel="Source model or system-defined profile" value={src} onChange={setSrc} loading={sys.loading} options={[...srcOptions, ...models.options.map((o) => ({ ...o, value: `arn:aws:bedrock:us-east-1::foundation-model/${o.value}` }))]} />
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="inference profile" names={sel.map((p) => p.inferenceProfileName)}
        onConfirm={async () => { await api.deleteProfile(sel[0].inferenceProfileId); setSel([]); app.reload(); }} />
    </Page>
  );
}
