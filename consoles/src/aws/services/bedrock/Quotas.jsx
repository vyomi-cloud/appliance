/* Bedrock > Quotas (capture 007): "Quotas by model" with Provider / Inference type filters. Rows come from ListFoundationModels. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Grid from "@cloudscape-design/components/grid";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const ANY_P = { label: "Any provider", value: "" }, ANY_I = { label: "Any inference type", value: "" };
export default function Quotas() {
  const t = useAsync(() => api.listModels(), []);
  const [prov, setProv] = useState(ANY_P);
  const [inf, setInf] = useState(ANY_I);
  const all = (t.data || []).flatMap((m) => (m.inferenceTypesSupported || ["ON_DEMAND"]).map((it) => ({ id: `${m.modelId}/${it}`, name: m.modelName, provider: m.providerName, type: it })));
  const provs = [ANY_P, ...[...new Set(all.map((x) => x.provider))].sort().map((p) => ({ label: p, value: p }))];
  const types = [ANY_I, ...[...new Set(all.map((x) => x.type))].sort().map((p) => ({ label: p === "ON_DEMAND" ? "On-demand" : p, value: p }))];
  const items = all.filter((x) => (!prov.value || x.provider === prov.value) && (!inf.value || x.type === inf.value));
  return (
    <ContentLayout header={<Header variant="h1" description={<>View approved model quotas for your account and request quota increases. <Link external>Learn more</Link></>}>Quotas</Header>}>
      <ResourceTable variant="container" resourceName="Quotas by model" trackBy="id" items={items} loading={t.loading} error={t.error} onRefresh={t.reload} filterPlaceholder="Find quotas"
        empty={{ title: "No quotas", subtitle: "No models match the selected filters." }}
        actions={<Button>View open increase requests</Button>}
        description={<Grid gridDefinition={[{ colspan: 4 }, { colspan: 4 }]}><SpaceBetween size="xxs"><Box variant="awsui-key-label">Provider</Box><Select selectedOption={prov} onChange={({ detail }) => setProv(detail.selectedOption)} options={provs} ariaLabel="Provider" /></SpaceBetween><SpaceBetween size="xxs"><Box variant="awsui-key-label">Inference type</Box><Select selectedOption={inf} onChange={({ detail }) => setInf(detail.selectedOption)} options={types} ariaLabel="Inference type" /></SpaceBetween></Grid>}
        columns={[
          { id: "name", header: "Model name", isRowHeader: true, sortingField: "name", cell: (x) => x.name },
          { id: "prov", header: "Provider", sortingField: "provider", cell: (x) => x.provider },
          { id: "type", header: "Inference type", cell: (x) => (x.type === "ON_DEMAND" ? "On-demand" : x.type) },
          { id: "tpm", header: "TPM", cell: () => "Not enforced" },
          { id: "rpm", header: "RPM", cell: () => "Not enforced" },
          { id: "req", header: "Request quota increase", cell: () => <Link>Request increase</Link> },
        ]} />
    </ContentLayout>
  );
}
