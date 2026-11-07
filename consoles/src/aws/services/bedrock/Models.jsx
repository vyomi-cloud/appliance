import Badge from "@cloudscape-design/components/badge";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { availText } from "../../../common/aiModels.js";

export default function Models() {
  const t = useAsync(() => api.listModels(), []);
  return (
    <ResourceTable resourceName="Foundation models" description="The ten open models of the Vyomi model pool. Only the small local model runs without a booster; the rest need the booster (Pro/Max)."
      items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="modelId" filterPlaceholder="Find models"
      columns={[
        { id: "name", header: "Model", isRowHeader: true, sortingField: "modelName", cell: (m) => m.modelName },
        { id: "id", header: "Model ID", sortingField: "modelId", cell: (m) => m.modelId },
        { id: "prov", header: "Provider", sortingField: "providerName", cell: (m) => m.providerName },
        { id: "in", header: "Input", cell: (m) => (m.inputModalities || []).map((x) => <Badge key={x}>{x}</Badge>) },
        { id: "out", header: "Output", cell: (m) => (m.outputModalities || []).map((x) => <Badge key={x}>{x}</Badge>) },
        { id: "avail", header: "Availability", cell: (m) => availText(m.vyomiAvailability, String(m.modelId).replace(/^vyomi\./, "")) },
        { id: "stream", header: "Streaming", cell: (m) => (m.responseStreamingSupported ? "Yes" : "No") },
      ]} />
  );
}
