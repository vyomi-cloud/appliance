/* Bedrock agents: create/prepare/alias, attach knowledge bases, and chat through InvokeAgent. */
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
import Textarea from "@cloudscape-design/components/textarea";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";
import { NOVA, stat, modelOption } from "./Common.jsx";

function CreateAgent({ visible, onDismiss }) {
  const models = useAsync(() => api.listModels(), []);
  const [name, setName] = useState("");
  const [model, setModel] = useState(null);
  const [instr, setInstr] = useState("You are a helpful assistant. Answer briefly and use the knowledge base when it is relevant.");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const opts = (models.data || []).filter((m) => m.outputModalities?.includes("TEXT")).map(modelOption);
  const sel = model || opts.find((o) => o.value === NOVA) || opts[0];
  const go = async () => {
    setBusy(true); setError(null);
    try { const a = await api.createAgent({ agentName: name, foundationModel: sel.value, instruction: instr }); onDismiss(); navigate("bedrock", "agents", a.agentId); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create agent" size="medium"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name || !sel} onClick={go}>Create</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} header="Couldn't create agent" />}
        <FormField label="Agent name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Agent name" /></FormField>
        <FormField label="Model"><Select selectedOption={sel || null} onChange={({ detail }) => setModel(detail.selectedOption)} options={opts} ariaLabel="Model" /></FormField>
        <FormField label="Instructions for the agent" constraintText="At least 40 characters"><Textarea value={instr} rows={4} onChange={({ detail }) => setInstr(detail.value)} ariaLabel="Instructions" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

export function Agents() {
  const t = useAsync(() => api.listAgents(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const notify = useNotify();
  return (
    <>
      <ResourceTable resourceName="Agents" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="agentId" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
        empty={{ title: "No agents", action: <Button onClick={() => setCreate(true)}>Create agent</Button> }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "agentName", cell: (a) => <Link href={href("bedrock", "agents", a.agentId)} onFollow={follow}>{a.agentName}</Link> },
          { id: "id", header: "Agent ID", cell: (a) => a.agentId },
          { id: "st", header: "Status", cell: (a) => stat(a.agentStatus) },
          { id: "upd", header: "Last updated", cell: (a) => a.updatedAt },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button><Button variant="primary" onClick={() => setCreate(true)}>Create agent</Button></SpaceBetween>} />
      <CreateAgent visible={create} onDismiss={() => { setCreate(false); t.reload(); }} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="agent" names={sel.map((a) => a.agentName)}
        onConfirm={async () => { await api.deleteAgent(sel[0].agentId); notify.success("Agent deleted."); setSel([]); t.reload(); }} />
    </>
  );
}

export function AgentDetail({ params }) {
  const id = params.id;
  const notify = useNotify();
  const ag = useAsync(() => api.getAgent(id), [id]);
  const al = useAsync(() => api.listAliases(id), [id]);
  const lk = useAsync(() => api.listAgentKbs(id), [id]);
  const kbs = useAsync(() => api.listKnowledgeBases(), []);
  const [aliasName, setAliasName] = useState("");
  const [kb, setKb] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState("");
  const [session] = useState(() => "sess-" + Math.random().toString(36).slice(2, 10));
  const a = ag.data;
  const run = async (key, fn, ok) => { setBusy(key); try { await fn(); if (ok) notify.success(ok); ag.reload(); al.reload(); lk.reload(); } catch (e) { notify.error(e); } finally { setBusy(""); } };
  const send = async () => {
    const text = input; setInput(""); setBusy("chat"); setMsgs((m) => [...m, { r: "user", t: text }]);
    try { const r = await api.invokeAgent(id, "TSTALIASID", session, text); setMsgs((m) => [...m, { r: "agent", t: r.text, c: r.citations.length }]); }
    catch (e) { setMsgs((m) => [...m, { r: "error", t: `${e.code}: ${e.message}` }]); } finally { setBusy(""); }
  };
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button variant="primary" loading={busy === "prep"} onClick={() => run("prep", () => api.prepareAgent(id), "Agent prepared.")}>Prepare</Button>}>{a?.agentName || id}</Header>}>
      <SpaceBetween size="l">
        {ag.error && <ErrorAlert error={ag.error} />}
        {a && <Container header={<Header variant="h2">Agent overview</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <div><Box variant="awsui-key-label">Status</Box>{stat(a.agentStatus)}</div>
            <div><Box variant="awsui-key-label">Model</Box>{a.foundationModel}</div>
            <div><Box variant="awsui-key-label">ARN</Box>{a.agentArn}</div>
          </ColumnLayout><Box margin={{ top: "s" }}><Box variant="awsui-key-label">Instructions</Box>{a.instruction}</Box></Container>}
        <CapabilityContainer id="bedrock.agents" title="Knowledge bases">
          <SpaceBetween size="s">
            <Table variant="embedded" items={lk.data || []} trackBy="knowledgeBaseId" empty={<Box textAlign="center">No knowledge bases associated</Box>}
              columnDefinitions={[{ id: "id", header: "Knowledge base", cell: (k) => (kbs.data || []).find((x) => x.knowledgeBaseId === k.knowledgeBaseId)?.name || k.knowledgeBaseId, isRowHeader: true }, { id: "d", header: "Description", cell: (k) => k.description }, { id: "s", header: "State", cell: (k) => stat(k.knowledgeBaseState) },
                { id: "x", header: "", cell: (k) => <Button variant="inline-link" onClick={() => run("dis", () => api.disassociateKb(id, k.knowledgeBaseId), "Knowledge base removed (re-prepare the agent).")}>Remove</Button> }]} />
            <SpaceBetween direction="horizontal" size="xs">
              <Select selectedOption={kb} onChange={({ detail }) => setKb(detail.selectedOption)} options={(kbs.data || []).map((k) => ({ label: k.name, value: k.knowledgeBaseId }))} placeholder="Choose a knowledge base" ariaLabel="Knowledge base" />
              <Button disabled={!kb} onClick={() => run("assoc", () => api.associateKb(id, kb.value, `Knowledge base ${kb.label}`), "Knowledge base associated (re-prepare the agent).")}>Add</Button>
            </SpaceBetween>
          </SpaceBetween>
        </CapabilityContainer>
        <Container header={<Header variant="h2">Aliases</Header>}>
          <SpaceBetween size="s">
            <Table variant="embedded" items={al.data || []} trackBy="agentAliasId" empty={<Box textAlign="center">No aliases</Box>}
              columnDefinitions={[{ id: "n", header: "Alias", cell: (x) => x.agentAliasName, isRowHeader: true }, { id: "i", header: "Alias ID", cell: (x) => x.agentAliasId }, { id: "v", header: "Version", cell: (x) => x.routingConfiguration?.[0]?.agentVersion }, { id: "s", header: "Status", cell: (x) => stat(x.agentAliasStatus) },
                { id: "x", header: "", cell: (x) => <Button variant="inline-link" onClick={() => run("dal", () => api.deleteAlias(id, x.agentAliasId), "Alias deleted.")}>Delete</Button> }]} />
            <SpaceBetween direction="horizontal" size="xs"><Input value={aliasName} onChange={({ detail }) => setAliasName(detail.value)} placeholder="alias name" ariaLabel="Alias name" /><Button disabled={!aliasName} loading={busy === "alias"} onClick={() => run("alias", async () => { await api.createAlias(id, aliasName); setAliasName(""); }, "Alias created (snapshot of the prepared agent).")}>Create alias</Button></SpaceBetween>
          </SpaceBetween>
        </Container>
        <Container header={<Header variant="h2" description="Test window: runs the DRAFT agent through InvokeAgent.">Test agent</Header>}>
          <SpaceBetween size="s">
            {a && a.agentStatus !== "PREPARED" && <Alert type="info">Prepare the agent before testing it.</Alert>}
            <div data-testid="chat" style={{ minHeight: 60 }}>{msgs.map((m, i) => <Box key={i} color={m.r === "error" ? "text-status-error" : "inherit"}><b>{m.r === "user" ? "You" : m.r === "agent" ? "Agent" : "Error"}:</b> {m.t}{m.c ? ` [${m.c} citation block]` : ""}</Box>)}</div>
            <SpaceBetween direction="horizontal" size="xs"><Input value={input} onChange={({ detail }) => setInput(detail.value)} onKeyDown={({ detail }) => detail.key === "Enter" && input && send()} placeholder="Message the agent" ariaLabel="Message" /><Button variant="primary" loading={busy === "chat"} disabled={!input || a?.agentStatus !== "PREPARED"} onClick={send}>Send</Button></SpaceBetween>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
