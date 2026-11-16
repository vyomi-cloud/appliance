import Link from "@cloudscape-design/components/link";
import Badge from "@cloudscape-design/components/badge";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { availText } from "../../../common/aiModels.js";
import LicenceChip from "../../../common/LicenceChip.jsx";

export default function Models() {
  const t = useAsync(() => api.listModels(), []);
  return (
    <ResourceTable resourceName="Model catalog" description="Models served by this simulator (Nano: in-browser WebLLM models; Mesh: the open-source pool). Only the small local model runs without the Mesh; the rest need the Mesh (Pro/Max). Models are open-source models from their publishers, not AWS or Amazon models; each keeps its own licence (see Notices and licences)."
      items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="modelId" filterPlaceholder="Find models"
      columns={[
        { id: "name", header: "Model", isRowHeader: true, sortingField: "modelName", cell: (m) => m.modelName },
        { id: "id", header: "Model ID", sortingField: "modelId", cell: (m) => m.modelId },
        { id: "prov", header: "Provider", sortingField: "providerName", cell: (m) => m.providerName },
        { id: "in", header: "Input", cell: (m) => (m.inputModalities || []).map((x) => <Badge key={x}>{x}</Badge>) },
        { id: "out", header: "Output", cell: (m) => (m.outputModalities || []).map((x) => <Badge key={x}>{x}</Badge>) },
        { id: "lic", header: "Licence", cell: (m) => <LicenceChip m={m} id={String(m.modelId).replace(/^vyomi\./, "")} /> },
        { id: "avail", header: "Availability", cell: (m) => availText(m.vyomiAvailability, String(m.modelId).replace(/^vyomi\./, "")) },
        { id: "play", header: "Playground", cell: (m) => <Link href="#/bedrock/playground">Open in playground</Link> },
        { id: "stream", header: "Streaming", cell: (m) => (m.responseStreamingSupported ? "Yes" : "No") },
      ]} />
  );
}
