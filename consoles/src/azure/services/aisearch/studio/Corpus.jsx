/* PRE-RAG visualisation: corpus health (before any query). Needs the inspect API (chunks) or the demo corpus. */
import { useMemo, useState } from "react";
import { Select } from "@fluentui/react-components";
import { corpusStats } from "../../../../common/ragstudio/engine.js";
import EmbeddingMap from "./EmbeddingMap.jsx";
import { Alert, Bars, Card, Grid, Stack, Tbl, Tile } from "./ui.jsx";

export const Unavailable = ({ err }) => <Alert type="info" title="Corpus views need the search inspect API">{err?.message || "No chunks available. Apply the design and ingest first."} The Vyomi extension is GET .../indexes/{"{index}"}/chunks; or choose the demo corpus.</Alert>;
const file = (u) => String(u).split("/").pop();

export default function Corpus({ data, proj, err }) {
  const [by, setBy] = useState("document"), [metaKey, setMetaKey] = useState("");
  const st = useMemo(() => (data ? corpusStats(data.chunks) : null), [data]);
  if (err || !data) return <Unavailable err={err} />;
  const keys = st.metaKeys.filter((k) => k !== "chunk_index"), mk = metaKey || keys[0] || "";
  return (
    <Stack gap={16}>
      <Card title="Corpus health" description={`Embedding model: ${data.embeddingModel}`}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: 12 }}>
          <Tile id="stat-docs" label="Documents" value={st.documents} /><Tile id="stat-chunks" label="Chunks" value={st.chunks} /><Tile label="Tokens" value={st.totalTokens} /><Tile id="stat-dups" label="Duplicate clusters" value={st.dupClusters.length} /><Tile id="stat-pii" label="Chunks with PII" value={st.piiChunks.length} />
        </div>
      </Card>
      <Grid cols={2}>
        <Card title="Chunk size histogram" description="Tokens per chunk; a long right tail or a spike at the limit means the splitter is cutting mid-thought."><div data-testid="hist-size"><Bars data={st.sizeHist.map((h) => [`${h.x}`, h.n])} /></div></Card>
        <Card title="Coverage by metadata" actions={keys.length ? <Select aria-label="coverage metadata key" value={mk} onChange={(_, d) => setMetaKey(d.value)}>{keys.map((k) => <option key={k}>{k}</option>)}</Select> : null}><div data-testid="coverage-meta">{mk ? <Bars data={Object.entries(st.byMeta(mk))} /> : "No metadata fields."}</div></Card>
      </Grid>
      <Card title="Coverage by source"><div data-testid="coverage-source"><Bars data={Object.entries(st.bySource)} /></div></Card>
      <Grid cols={2}>
        <Card title={`Duplicate and near-duplicate clusters (${st.dupClusters.length})`} description="3-word shingle Jaccard >= 0.6 across chunks.">
          <Tbl testid="dup-table" items={st.dupClusters.map((c, i) => ({ ...c, i }))} trackBy="i" empty="No duplicates." columns={[{ id: "u", header: "Documents", cell: (c) => c.uris.map(file).join(" <-> ") }, { id: "n", header: "Chunks", cell: (c) => c.ids.length }, { id: "e", header: "Kind", cell: (c) => (c.exact ? "exact" : "near") }]} />
        </Card>
        <Card title="Language and PII flags"><Stack gap={8}><div style={{ fontSize: 12 }}>Languages: {Object.entries(st.langs).map(([k, v]) => `${k} ${v}`).join(", ")}</div>
          <Tbl testid="pii-table" items={st.piiChunks} trackBy="id" empty="No PII detected." columns={[{ id: "u", header: "Document", cell: (c) => file(c.uri) }, { id: "k", header: "PII kinds", cell: (c) => c.pii.join(", ") }, { id: "t", header: "Chunk", cell: (c) => c.text.slice(0, 70) }]} /></Stack></Card>
      </Grid>
      <Card title="Embedding map" description={`${proj?.method === "backend" ? "PCA projection computed by the search service" : `UMAP (${proj?.method})`} of the chunk embeddings${proj?.sampled ? "; deterministic sample shown" : ""}. Nearby points are semantically close.`}
        actions={<Select aria-label="colour by" value={by} onChange={(_, d) => setBy(d.value)}><option value="document">Document</option>{keys.map((k) => <option key={k}>{k}</option>)}<option value="language">Language</option><option value="pii">PII</option></Select>}>
        {proj ? <EmbeddingMap points={proj.points} chunks={data.chunks} colorBy={by} /> : <span>Projecting...</span>}
      </Card>
    </Stack>
  );
}
