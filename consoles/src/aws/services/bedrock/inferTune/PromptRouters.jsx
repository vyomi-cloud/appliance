/* Prompt routers (Configured / Default tabs). Routing between two models is recorded; Converse/InvokeModel on a router ARN answer with the larger model. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import DeleteModal from "../../../kit/DeleteModal.jsx";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import { navigate } from "../../../../common/router.js";
import * as api from "./api.js";
import { CreateModal, Field, HowItWorks, ModelSelect, Page, modelOf, useModelOptions, when } from "./Shared.jsx";

const shortName = (arn) => modelOf(arn).replace(/^(us|eu|apac)\./, "");

export default function PromptRouters() {
  const notify = useNotify();
  const custom = useAsync(() => api.listRouters("custom"), []);
  const dflt = useAsync(() => api.listRouters("default"), []);
  const models = useModelOptions();
  const [tab, setTab] = useState("configured");
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false), [del, setDel] = useState(false);
  const [name, setName] = useState(""), [m1, setM1] = useState(null), [m2, setM2] = useState(null), [q, setQ] = useState("0.1"), [fb, setFb] = useState(null);
  const arn = (id) => `arn:aws:bedrock:us-east-1:${api.ACCOUNT}:inference-profile/us.${id}`;
  const configure = <Button variant="primary" onClick={() => setOpen(true)}>Configure prompt router</Button>;
  const updated = new Date().toUTCString().replace(/ GMT$/, " UTC");
  return (
    <Page title="Prompt Routers" description="Route requests between foundational models from the same family, optimizing for response quality and cost.">
      <HowItWorks steps={[
        { title: "Experiment with default routers", body: "Choose from prompt routers that route requests between Claude Sonnet 3.5 and Claude Haiku, or between Llama 3.1 7B and Llama 3.1 80B." },
        { title: "Configure prompt router", body: "Set up the router to route requests between specific models, ensuring full control over models used in your applications.", action: <Button onClick={() => setOpen(true)}>Configure router</Button> },
        { title: "Use for production", body: "Save time on testing and complex orchestration workflows. Use Invoke and Converse API operations to incorporate routers into generative AI applications." },
      ]} />
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "configured", label: "Configured", content:
          <ResourceTable variant="container" resourceName="Configured prompt routers" description="Configure your own router by choosing specific models and routing criteria." items={custom.data || []} loading={custom.loading} error={custom.error} onRefresh={custom.reload}
            trackBy="promptRouterArn" selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Find prompt routers"
            actions={<><Box variant="small" textAlign="right">Last Updated<br />{updated}</Box><ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>{configure}</>}
            empty={{ title: "No prompt routers", subtitle: "There are currently no resources.", action: <Button onClick={() => setOpen(true)}>Configure prompt router</Button> }}
            columns={[
              { id: "name", header: "Name", isRowHeader: true, sortingField: "promptRouterName", cell: (r) => r.promptRouterName },
              { id: "crit", header: "Routing criteria", cell: (r) => `Response quality difference: ${Math.round((r.routingCriteria?.responseQualityDifference || 0) * 100)}%` },
              { id: "models", header: "Selected models", cell: (r) => (r.models || []).map((m) => shortName(m.modelArn)).join(", ") },
              { id: "created", header: "Created at", sortingField: "createdAt", cell: (r) => when(r.createdAt) },
            ]} /> },
        { id: "default", label: "Default", content:
          <Container header={<Header variant="h2" counter={`(${(dflt.data || []).length})`} description="Bedrock offers pre-configured prompt routers for different model providers."
            actions={<SpaceBetween direction="horizontal" size="xs"><Box variant="small" textAlign="right">Last Updated<br />{updated}</Box><Button onClick={() => navigate("bedrock", "playground")}>Open in playground</Button></SpaceBetween>}>Default routers</Header>}>
            <ColumnLayout columns={2} variant="text-grid">
              {(dflt.data || []).map((r) => (
                <Container key={r.promptRouterArn} header={<Header variant="h3">{r.promptRouterName}</Header>}>
                  <SpaceBetween size="s">
                    <div><Box variant="awsui-key-label">Routing models</Box><div>{(r.models || []).map((m) => shortName(m.modelArn)).join(", ")}</div></div>
                    <div><Box variant="awsui-key-label">Routing criteria</Box><div>Response quality difference: {Math.round((r.routingCriteria?.responseQualityDifference || 0) * 100)}%</div></div>
                    <div><Box variant="awsui-key-label">ARN</Box><div>{r.promptRouterArn}</div></div>
                  </SpaceBetween>
                </Container>))}
            </ColumnLayout>
          </Container> },
      ]} />
      <CreateModal visible={open} onDismiss={() => setOpen(false)} header="Configure prompt router" submitLabel="Configure" disabled={!name || !m1 || !m2 || m1 === m2 || !fb}
        onSubmit={async () => { await api.createRouter(name, [arn(m1), arn(m2)], q, arn(fb)); notify.success(`Prompt router "${name}" configured.`); setTab("configured"); custom.reload(); }}>
        <Field label="Router name" value={name} onChange={setName} />
        <FormField label="Model 1"><ModelSelect ariaLabel="Model 1" value={m1} onChange={setM1} {...models} /></FormField>
        <FormField label="Model 2" description="Choose two models from the same family."><ModelSelect ariaLabel="Model 2" value={m2} onChange={setM2} {...models} /></FormField>
        <Field label="Response quality difference (0 to 1)" description="How much quality difference is acceptable before routing to the more capable model." type="number" value={q} onChange={setQ} />
        <FormField label="Fallback model"><ModelSelect ariaLabel="Fallback model" value={fb} onChange={setFb} {...models} /></FormField>
      </CreateModal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="prompt router" names={sel.map((r) => r.promptRouterName)} onConfirm={async () => { await api.deleteRouter(sel[0].promptRouterArn); setSel([]); custom.reload(); }} />
    </Page>
  );
}
