/* PRE-RAG visualisation: corpus health (before any query). */
import { useMemo, useState } from "react";
import { Alert, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { corpusStats } from "../../../../common/ragstudio/engine.js";
import EmbeddingMap, { fileOf } from "./EmbeddingMap.jsx";
import { Bars, Card, Tbl, Tile } from "./ui.jsx";

export const Unavailable = ({ err }) => <Alert severity="info">Corpus views need the Vyomi inspect API. {err?.message || "No chunks available."} The simulator serves GET /_vyomi/gcp-rag/&#123;project&#125;/&#123;location&#125;/&#123;corpusId&#125;/chunks; or choose the demo corpus.</Alert>;

export default function Corpus({ data, proj, err }) {
  const [by, setBy] = useState("document"), [metaKey, setMetaKey] = useState("file");
  const st = useMemo(() => (data ? corpusStats(data.chunks) : null), [data]);
  if (err || !data) return <Unavailable err={err} />;
  const keys = st.metaKeys.filter((k) => k !== "chunk_index");
  const hist = Object.fromEntries(st.sizeHist.map((h) => [`${h.x}+ tokens`, h.n]));
  return (
    <Stack spacing={2}>
      <Card title="Corpus health" description={`Embedding model: ${data.embeddingModel}`}>
        <Stack direction="row" useFlexGap spacing={4} sx={{ flexWrap: "wrap" }}>
          <Tile id="stat-docs" label="Documents" value={st.documents} /><Tile id="stat-chunks" label="Chunks" value={st.chunks} /><Tile label="Tokens" value={st.totalTokens} /><Tile id="stat-dups" label="Duplicate clusters" value={st.dupClusters.length} /><Tile id="stat-pii" label="Chunks with PII" value={st.piiChunks.length} />
        </Stack>
      </Card>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Card title="Chunk size histogram" description="Tokens per chunk; a long tail or a spike at the limit means the chunker is cutting mid-thought." sx={{ flex: 1 }} data-testid="hist-size"><Bars data={hist} /></Card>
        <Card title="Coverage by metadata" sx={{ flex: 1 }} actions={<TextField select size="small" value={keys.includes(metaKey) ? metaKey : keys[0] || ""} onChange={(e) => setMetaKey(e.target.value)} sx={{ minWidth: 130 }}>{keys.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}</TextField>}>
          <Bars data={st.byMeta(keys.includes(metaKey) ? metaKey : keys[0])} />
        </Card>
      </Stack>
      <Card title="Coverage by source" data-testid="coverage-source"><Bars data={st.bySource} /></Card>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Card title={`Duplicate and near-duplicate clusters (${st.dupClusters.length})`} description="3-word shingle Jaccard >= 0.6 across chunks." sx={{ flex: 1 }}>
          <Tbl data-testid="dup-table" rows={st.dupClusters} empty="No duplicates." columns={[{ id: "u", header: "Documents", cell: (c) => c.uris.map(fileOf).join(" <-> ") }, { id: "n", header: "Chunks", cell: (c) => c.ids.length }, { id: "e", header: "Exact", cell: (c) => (c.exact ? "yes" : "near") }]} />
        </Card>
        <Card title="Language and PII flags" sx={{ flex: 1 }}>
          <Typography variant="caption" component="div" sx={{ mb: 1 }}>Languages: {Object.entries(st.langs).map(([k, v]) => `${k} ${v}`).join(", ")}</Typography>
          <Tbl data-testid="pii-table" rows={st.piiChunks} empty="No PII detected." rowKey={(c) => c.id} columns={[{ id: "u", header: "Document", cell: (c) => fileOf(c.uri) }, { id: "k", header: "PII kinds", cell: (c) => (c.pii?.length ? c.pii : ["email"]).join(", ") }, { id: "t", header: "Chunk", cell: (c) => c.text.slice(0, 80) }]} />
        </Card>
      </Stack>
      <Card title="Embedding map" description={`${proj?.method === "backend" ? "PCA (computed by the inspect API)" : `UMAP (${proj?.method})`} projection of the chunk embeddings${proj?.sampled ? "; deterministic sample shown" : ""}. Nearby points are semantically close.`}
        actions={<TextField select size="small" label="Colour by" value={by} onChange={(e) => setBy(e.target.value)} sx={{ minWidth: 150 }}>{["document", ...keys, "language", "pii"].map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}</TextField>}>
        {proj ? <EmbeddingMap points={proj.points} chunks={data.chunks} colorBy={by} /> : <Typography variant="body2">Projecting...</Typography>}
      </Card>
    </Stack>
  );
}
