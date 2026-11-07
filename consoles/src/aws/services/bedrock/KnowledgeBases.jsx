/* Knowledge bases: S3 data sources ingested (chunk + embed) into the account's vector index; test retrieval + generation. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";
import { NOVA, TITAN, modelArn, stat } from "./Common.jsx";

function CreateKb({ visible, onDismiss }) {
  const notify = useNotify();
  const buckets = useAsync(() => api.listBuckets(), []);
  const [name, setName] = useState("");
  const [bucket, setBucket] = useState(null);
  const [prefix, setPrefix] = useState("");
  const [tokens, setTokens] = useState("300");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try {
      const kb = await api.createKnowledgeBase(name, TITAN);
      const ds = await api.createDataSource(kb.knowledgeBaseId, `${name}-s3`, bucket.value, prefix, tokens);
      const job = await api.startIngestion(kb.knowledgeBaseId, ds.dataSourceId);
      notify.success(`Knowledge base "${name}" created; ${job.statistics.numberOfNewDocumentsIndexed} document(s) indexed.`);
      onDismiss(); navigate("bedrock", "knowledge-bases", kb.knowledgeBaseId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create knowledge base" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name || !bucket} onClick={go}>Create and sync</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} header="Couldn't create knowledge base" />}
        <FormField label="Knowledge base name" constraintText="Letters, numbers, hyphens and underscores"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Knowledge base name" /></FormField>
        <FormField label="S3 bucket" description="Text documents (.txt .md .csv .json .html ...) in this bucket are chunked and embedded."><Select selectedOption={bucket} onChange={({ detail }) => setBucket(detail.selectedOption)} options={(buckets.data || []).map((b) => ({ label: b, value: b }))} statusType={buckets.loading ? "loading" : "finished"} placeholder="Choose a bucket" ariaLabel="S3 bucket" empty="No buckets" /></FormField>
        <FormField label="Key prefix - optional"><Input value={prefix} onChange={({ detail }) => setPrefix(detail.value)} ariaLabel="Key prefix" placeholder="docs/" /></FormField>
        <FormField label="Chunk size (tokens)"><Input type="number" value={tokens} onChange={({ detail }) => setTokens(detail.value)} ariaLabel="Chunk size" /></FormField>
        <Box variant="small">Embedding model: Nomic Embed Text (computed locally).</Box>
      </SpaceBetween>
    </Modal>
  );
}

export function KnowledgeBases() {
  const t = useAsync(() => api.listKnowledgeBases(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const notify = useNotify();
  return (
    <>
      <ResourceTable resourceName="Knowledge bases" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="knowledgeBaseId"
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} empty={{ title: "No knowledge bases", action: <Button onClick={() => setCreate(true)}>Create knowledge base</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (k) => <Link href={href("bedrock", "knowledge-bases", k.knowledgeBaseId)} onFollow={follow}>{k.name}</Link> },
          { id: "id", header: "Knowledge base ID", cell: (k) => k.knowledgeBaseId },
          { id: "status", header: "Status", cell: (k) => stat(k.status) },
          { id: "upd", header: "Last updated", cell: (k) => k.updatedAt },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button><Button variant="primary" onClick={() => setCreate(true)}>Create knowledge base</Button></SpaceBetween>} />
      <CreateKb visible={create} onDismiss={() => { setCreate(false); t.reload(); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="knowledge base" names={sel.map((k) => k.name)}
        onConfirm={async () => { await api.deleteKnowledgeBase(sel[0].knowledgeBaseId); notify.success("Knowledge base deleted."); setSel([]); t.reload(); }} />
    </>
  );
}

export function KnowledgeBaseDetail({ params }) {
  const id = params.id;
  const notify = useNotify();
  const kb = useAsync(() => api.getKnowledgeBase(id), [id]);
  const ds = useAsync(() => api.listDataSources(id), [id]);
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState("");
  const sync = async (d) => {
    setBusy(d.dataSourceId);
    try { const j = await api.startIngestion(id, d.dataSourceId); const s = j.statistics; notify.success(`Sync complete: ${s.numberOfNewDocumentsIndexed} indexed, ${s.numberOfDocumentsFailed} failed.`); if (j.failureReasons?.length) notify.info(j.failureReasons[0]); }
    catch (e) { notify.error(e); } finally { setBusy(""); }
  };
  const test = async (gen) => {
    setBusy(gen ? "gen" : "ret"); setError(null); setRes(null); setAnswer(null);
    try { if (gen) setAnswer(await api.retrieveAndGenerate(id, q, modelArn(NOVA))); else setRes(await api.retrieve(id, q, 5)); } catch (e) { setError(e); } finally { setBusy(""); }
  };
  const k = kb.data;
  return (
    <ContentLayout header={<Header variant="h1">{k?.name || id}</Header>}>
      <SpaceBetween size="l">
        {kb.error && <ErrorAlert error={kb.error} />}
        {k && <Container header={<Header variant="h2">Knowledge base overview</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <div><Box variant="awsui-key-label">Status</Box>{stat(k.status)}</div>
            <div><Box variant="awsui-key-label">ARN</Box>{k.knowledgeBaseArn}</div>
            <div><Box variant="awsui-key-label">Embeddings model</Box>{k.knowledgeBaseConfiguration.vectorKnowledgeBaseConfiguration.embeddingModelArn.split("/").pop()}</div>
          </ColumnLayout></Container>}
        <CapabilityContainer id="bedrock.knowledge-bases" title="Data sources">
          <Table items={ds.data || []} loading={ds.loading} trackBy="dataSourceId" variant="embedded" empty={<Box textAlign="center">No data sources</Box>}
            columnDefinitions={[{ id: "n", header: "Name", cell: (d) => d.name, isRowHeader: true }, { id: "s", header: "Status", cell: (d) => stat(d.status) }, { id: "u", header: "Last updated", cell: (d) => d.updatedAt },
              { id: "a", header: "Actions", cell: (d) => <Button loading={busy === d.dataSourceId} onClick={() => sync(d)}>Sync</Button> }]} />
        </CapabilityContainer>
        <Container header={<Header variant="h2" description="Retrieve ranks chunks by embedding similarity; Retrieve and generate answers from them with the local model.">Test knowledge base</Header>}>
          <SpaceBetween size="s">
            <FormField label="Query"><Input value={q} onChange={({ detail }) => setQ(detail.value)} ariaLabel="Query" placeholder="Ask about your documents" /></FormField>
            <SpaceBetween direction="horizontal" size="xs"><Button loading={busy === "ret"} disabled={!q} onClick={() => test(false)}>Retrieve</Button><Button loading={busy === "gen"} disabled={!q} onClick={() => test(true)}>Retrieve and generate</Button></SpaceBetween>
            {error && <Alert type="error" header={error.code}>{error.message}</Alert>}
            {answer && <Alert type="success" header="Generated response"><span data-testid="rag-answer">{answer.output.text}</span></Alert>}
            {res && (res.length ? <Table variant="embedded" items={res.map((r, i) => ({ ...r, _i: i }))} trackBy="_i" columnDefinitions={[
              { id: "score", header: "Score", cell: (r) => r.score.toFixed(3) }, { id: "uri", header: "Source", cell: (r) => r.location.s3Location.uri }, { id: "txt", header: "Chunk", cell: (r) => r.content.text.slice(0, 160) }]} /> : <Box>No results (sync a data source first).</Box>)}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
