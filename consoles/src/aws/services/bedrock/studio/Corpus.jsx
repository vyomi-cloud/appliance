/* PRE-RAG visualisation: corpus health (before any query). */
import { useMemo, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import BarChart from "@cloudscape-design/components/bar-chart";
import Box from "@cloudscape-design/components/box";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import EmbeddingMap from "./EmbeddingMap.jsx";
import { corpusStats } from "./engine.js";

export const Unavailable = ({ err }) => <Alert type="info" header="Corpus views need the knowledge inspect API">{err?.message || "No chunks available."} Start the knowledge lane build (GET /_vyomi/kb/&#123;id&#125;/chunks) or choose the demo corpus.</Alert>;
const Tile = ({ label, value, id }) => <div><Box variant="awsui-key-label">{label}</Box><Box variant="h1" data-testid={id}>{value}</Box></div>;

export default function Corpus({ data, proj, err }) {
  const [by, setBy] = useState({ label: "Document", value: "document" });
  const st = useMemo(() => (data ? corpusStats(data.chunks) : null), [data]);
  const [metaKey, setMetaKey] = useState({ label: "department", value: "department" });
  if (err || !data) return <Unavailable err={err} />;
  const colorOpts = [{ label: "Document", value: "document" }, ...st.metaKeys.filter((k) => k !== "chunk_index").map((k) => ({ label: k, value: k })), { label: "Language", value: "language" }, { label: "PII", value: "pii" }];
  const bars = (obj, title) => <BarChart height={220} hideFilter xScaleType="categorical" ariaLabel={title} xTitle={title} yTitle="Chunks" series={[{ title: "Chunks", type: "bar", data: Object.entries(obj).map(([x, y]) => ({ x, y })) }]} />;
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" description={`Embedding model: ${data.embeddingModel}`}>Corpus health</Header>}>
        <ColumnLayout columns={5} variant="text-grid">
          <Tile id="stat-docs" label="Documents" value={st.documents} /><Tile id="stat-chunks" label="Chunks" value={st.chunks} /><Tile label="Tokens" value={st.totalTokens} /><Tile id="stat-dups" label="Duplicate clusters" value={st.dupClusters.length} /><Tile id="stat-pii" label="Chunks with PII" value={st.piiChunks.length} />
        </ColumnLayout>
      </Container>
      <ColumnLayout columns={2}>
        <Container header={<Header variant="h2" description="Tokens per chunk; a long right tail or a spike at the limit means the chunker is cutting mid-thought.">Chunk size histogram</Header>}><div data-testid="hist-size"><BarChart height={220} hideFilter xScaleType="categorical" ariaLabel="chunk token histogram" xTitle="Tokens per chunk (bin start)" yTitle="Chunks" series={[{ title: "Chunks", type: "bar", data: st.sizeHist.map((b) => ({ x: String(b.x), y: b.n })) }]} /></div></Container>
        <Container header={<Header variant="h2" actions={<Select selectedOption={metaKey} onChange={({ detail }) => setMetaKey(detail.selectedOption)} options={st.metaKeys.filter((k) => k !== "chunk_index").map((k) => ({ label: k, value: k }))} ariaLabel="coverage metadata key" />}>Coverage by metadata</Header>}><div data-testid="coverage-meta">{bars(st.byMeta(metaKey.value), metaKey.value)}</div></Container>
      </ColumnLayout>
      <Container header={<Header variant="h2">Coverage by source</Header>}><div data-testid="coverage-source">{bars(st.bySource, "document")}</div></Container>
      <ColumnLayout columns={2}>
        <Container header={<Header variant="h2" counter={`(${st.dupClusters.length})`} description="3-word shingle Jaccard >= 0.6 across chunks.">Duplicate and near-duplicate clusters</Header>}>
          <Table variant="embedded" data-testid="dup-table" items={st.dupClusters.map((c, i) => ({ ...c, i }))} trackBy="i" empty={<Box>No duplicates.</Box>} columnDefinitions={[{ id: "u", header: "Documents", cell: (c) => c.uris.map((u) => u.split("/").pop()).join(" <-> ") }, { id: "n", header: "Chunks", cell: (c) => c.ids.length }, { id: "e", header: "Kind", cell: (c) => (c.exact ? "exact" : "near") }]} />
        </Container>
        <Container header={<Header variant="h2" description="Language and PII per chunk.">Language and PII flags</Header>}>
          <SpaceBetween size="s"><Box variant="small">Languages: {Object.entries(st.langs).map(([k, v]) => `${k} ${v}`).join(", ")}</Box>
            <Table variant="embedded" data-testid="pii-table" items={st.piiChunks} trackBy="id" empty={<Box>No PII detected.</Box>} columnDefinitions={[{ id: "u", header: "Document", cell: (c) => c.uri.split("/").pop() }, { id: "k", header: "PII kinds", cell: (c) => c.pii.join(", ") }, { id: "t", header: "Chunk", cell: (c) => c.text.slice(0, 70) }]} /></SpaceBetween>
        </Container>
      </ColumnLayout>
      <Container header={<Header variant="h2" description={`UMAP (${proj?.method}) projection of the chunk embeddings${proj?.sampled ? "; deterministic sample shown" : ""}. Nearby points are semantically close.`} actions={<Select selectedOption={by} onChange={({ detail }) => setBy(detail.selectedOption)} options={colorOpts} ariaLabel="colour by" />}>Embedding map</Header>}>
        {proj ? <EmbeddingMap points={proj.points} chunks={data.chunks} colorBy={by.value} /> : <Box>Projecting...</Box>}
      </Container>
    </SpaceBetween>
  );
}
