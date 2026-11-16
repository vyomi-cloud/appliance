/* Bedrock agents: create/prepare/alias, attach knowledge bases, and chat through InvokeAgent. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Checkbox from "@cloudscape-design/components/checkbox";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
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


const BUILTIN = { "AMAZON.UserInput": "Ask the user for missing information (AMAZON.UserInput)", "AMAZON.CodeInterpreter": "Code interpreter: write and run Python (AMAZON.CodeInterpreter)" };
const FN_EXAMPLE = '{"functions":[{"name":"get_room_status","description":"Look up a room","parameters":{"room":{"type":"string","required":true}},"requireConfirmation":"DISABLED"}]}';

function CreateActionGroup({ visible, onDismiss, agentId, onDone }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState({ label: "Define with function details (Lambda)", value: "fn" });
  const [lambdaArn, setLambdaArn] = useState("");
  const [schema, setSchema] = useState(FN_EXAMPLE);
  const [bucket, setBucket] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const k = kind.value;
  const kinds = [{ label: "Define with function details (Lambda)", value: "fn" }, { label: "Define with API schema (Lambda, OpenAPI JSON/YAML inline)", value: "api" },
    { label: "Define with API schema from S3 (Lambda)", value: "s3" }, { label: "Return control (the caller runs the action)", value: "rc" }, ...Object.entries(BUILTIN).map(([v, l]) => ({ label: l, value: v }))];
  const go = async () => {
    setBusy(true); setError(null);
    try {
      const body = { actionGroupName: name, actionGroupState: "ENABLED" };
      if (BUILTIN[k]) body.parentActionGroupSignature = k;
      else {
        body.actionGroupExecutor = k === "rc" ? { customControl: "RETURN_CONTROL" } : { lambda: lambdaArn };
        if (k === "s3") body.apiSchema = { s3: { s3BucketName: bucket, s3ObjectKey: key } };
        else if (k === "api") body.apiSchema = { payload: schema };
        else body.functionSchema = JSON.parse(schema);
      }
      await api.createActionGroup(agentId, body); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Add action group" size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name} onClick={go}>Add</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} header="Couldn't add action group" />}
        <FormField label="Action group name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Action group name" /></FormField>
        <FormField label="Action group type"><Select selectedOption={kind} onChange={({ detail }) => setKind(detail.selectedOption)} options={kinds} ariaLabel="Action group type" /></FormField>
        {(k === "fn" || k === "api" || k === "s3") && <FormField label="Lambda function ARN"><Input value={lambdaArn} onChange={({ detail }) => setLambdaArn(detail.value)} placeholder="arn:aws:lambda:us-east-1:123456789012:function:my-actions" ariaLabel="Lambda ARN" /></FormField>}
        {(k === "fn" || k === "api") && <FormField label={k === "fn" ? "Function schema (JSON; set requireConfirmation ENABLED on a function to ask the caller before it runs)" : "OpenAPI schema (JSON or YAML; x-requireConfirmation: ENABLED per operation)"}>
          <Textarea value={schema} rows={7} onChange={({ detail }) => setSchema(detail.value)} ariaLabel="Schema" /></FormField>}
        {k === "s3" && <ColumnLayout columns={2}><FormField label="S3 bucket"><Input value={bucket} onChange={({ detail }) => setBucket(detail.value)} ariaLabel="Schema bucket" /></FormField>
          <FormField label="S3 object key"><Input value={key} onChange={({ detail }) => setKey(detail.value)} ariaLabel="Schema key" /></FormField></ColumnLayout>}
        {BUILTIN[k] && <Alert type="info">{k === "AMAZON.CodeInterpreter" ? "Python runs in a restricted sandbox (no network, no host files). Input files are passed in sessionState.files; files the code writes come back as output files." : "The agent can ask the user a question; it is returned as the reply and the user's next message continues the session."}</Alert>}
      </SpaceBetween>
    </Modal>
  );
}

/** Compact, readable trace: one line per trace part with the interesting payload. */
function traceLines(traces) {
  const out = [];
  for (const ev of traces) {
    const who = ev.collaboratorName ? `[${ev.collaboratorName}] ` : "";
    const tr = ev.trace || {};
    for (const [part, body] of Object.entries(tr)) {
      if (part === "orchestrationTrace") {
        if (body.invocationInput) { const i = body.invocationInput; out.push(`${who}orchestration > invoke ${i.invocationType}${i.actionGroupInvocationInput ? ` ${i.actionGroupInvocationInput.actionGroupName}.${i.actionGroupInvocationInput.function || i.actionGroupInvocationInput.apiPath}` : ""}${i.codeInterpreterInvocationInput ? `: ${i.codeInterpreterInvocationInput.code.slice(0, 80)}` : ""}${i.agentCollaboratorInvocationInput ? ` ${i.agentCollaboratorInvocationInput.agentCollaboratorName}` : ""}`); }
        if (body.observation) { const o = body.observation; out.push(`${who}orchestration > observe ${o.type}: ${(o.actionGroupInvocationOutput?.text || o.codeInterpreterInvocationOutput?.executionOutput || o.agentCollaboratorInvocationOutput?.output?.text || o.finalResponse?.text || "").slice(0, 120)}`); }
        if (body.rationale) out.push(`${who}orchestration > rationale: ${body.rationale.text.slice(0, 120)}`);
        if (body.modelInvocationInput && !body.invocationInput) out.push(`${who}orchestration > model call`);
      } else out.push(`${who}${part}`);
    }
  }
  return out;
}

function ActionGroupsPanel({ agentId, onChange }) {
  const t = useAsync(() => api.listActionGroups(agentId), [agentId]);
  const [add, setAdd] = useState(false);
  const notify = useNotify();
  return (
    <Container header={<Header variant="h2" description="Lambda function / OpenAPI (inline or from S3), return-control, and the built-in user-input and code-interpreter groups." actions={<Button onClick={() => setAdd(true)}>Add action group</Button>}>Action groups</Header>}>
      <Table variant="embedded" items={t.data || []} trackBy="actionGroupId" empty={<Box textAlign="center">No action groups</Box>}
        columnDefinitions={[{ id: "n", header: "Name", cell: (g) => g.actionGroupName, isRowHeader: true }, { id: "s", header: "State", cell: (g) => stat(g.actionGroupState) }, { id: "d", header: "Description", cell: (g) => g.description },
          { id: "x", header: "", cell: (g) => <Button variant="inline-link" onClick={async () => { try { await api.deleteActionGroup(agentId, g.actionGroupId); notify.success("Action group deleted (re-prepare the agent)."); t.reload(); onChange(); } catch (e) { notify.error(e); } }}>Delete</Button> }]} />
      <CreateActionGroup visible={add} onDismiss={() => setAdd(false)} agentId={agentId} onDone={() => { t.reload(); onChange(); notify.success("Action group added (re-prepare the agent)."); }} />
    </Container>
  );
}

function CollaborationPanel({ agent, onChange }) {
  const notify = useNotify();
  const cs = useAsync(() => api.listCollaborators(agent.agentId), [agent.agentId, agent.agentCollaboration]);
  const agents = useAsync(() => api.listAgents(), []);
  const [other, setOther] = useState(null);
  const [alias, setAlias] = useState(null);
  const [aliases, setAliases] = useState([]);
  const [cname, setCname] = useState("");
  const [instr, setInstr] = useState("");
  const [relay, setRelay] = useState(false);
  const mode = agent.agentCollaboration || "DISABLED";
  const modes = [{ label: "Disabled", value: "DISABLED" }, { label: "Supervisor", value: "SUPERVISOR" }, { label: "Supervisor with routing", value: "SUPERVISOR_ROUTER" }];
  const pick = async (o) => { setOther(o); setAlias(null); try { const l = await api.listAliases(o.value); setAliases([{ label: "TSTALIASID (draft)", value: "TSTALIASID" }, ...l.map((x) => ({ label: x.agentAliasName, value: x.agentAliasId }))]); } catch (e) { notify.error(e); } };
  return (
    <Container header={<Header variant="h2" description="A supervisor agent delegates sub-requests to collaborator agents; with routing it can hand a whole request to one collaborator.">Multi-agent collaboration</Header>}>
      <SpaceBetween size="s">
        <FormField label="Collaboration mode"><Select selectedOption={modes.find((m) => m.value === mode)} options={modes} ariaLabel="Collaboration mode"
          onChange={async ({ detail }) => { try { await api.updateAgent(agent.agentId, agent, { agentCollaboration: detail.selectedOption.value }); notify.success("Collaboration mode saved (re-prepare the agent)."); onChange(); } catch (e) { notify.error(e); } }} /></FormField>
        {mode !== "DISABLED" && <>
          <Table variant="embedded" items={cs.data || []} trackBy="collaboratorId" empty={<Box textAlign="center">No collaborators</Box>}
            columnDefinitions={[{ id: "n", header: "Collaborator", cell: (c) => c.collaboratorName, isRowHeader: true }, { id: "a", header: "Alias", cell: (c) => c.agentDescriptor?.aliasArn?.split(":agent-alias/")[1] }, { id: "i", header: "Instruction", cell: (c) => c.collaborationInstruction }, { id: "r", header: "Relay history", cell: (c) => c.relayConversationHistory },
              { id: "x", header: "", cell: (c) => <Button variant="inline-link" onClick={async () => { try { await api.disassociateCollaborator(agent.agentId, c.collaboratorId); cs.reload(); onChange(); } catch (e) { notify.error(e); } }}>Remove</Button> }]} />
          <ColumnLayout columns={2}>
            <FormField label="Collaborator agent"><Select selectedOption={other} onChange={({ detail }) => pick(detail.selectedOption)} options={(agents.data || []).filter((x) => x.agentId !== agent.agentId).map((x) => ({ label: x.agentName, value: x.agentId }))} placeholder="Choose an agent" ariaLabel="Collaborator agent" /></FormField>
            <FormField label="Agent alias"><Select selectedOption={alias} onChange={({ detail }) => setAlias(detail.selectedOption)} options={aliases} placeholder="Choose an alias" ariaLabel="Collaborator alias" /></FormField>
            <FormField label="Collaborator name"><Input value={cname} onChange={({ detail }) => setCname(detail.value)} ariaLabel="Collaborator name" /></FormField>
            <FormField label="Collaborator instruction"><Input value={instr} onChange={({ detail }) => setInstr(detail.value)} placeholder="When to hand work to this agent" ariaLabel="Collaboration instruction" /></FormField>
          </ColumnLayout>
          <Checkbox checked={relay} onChange={({ detail }) => setRelay(detail.checked)}>Relay the conversation history to the collaborator</Checkbox>
          <Button disabled={!other || !alias || !cname || !instr} onClick={async () => {
            try { await api.associateCollaborator(agent.agentId, { agentDescriptor: { aliasArn: `arn:aws:bedrock:us-east-1:${api.ACCOUNT}:agent-alias/${other.value}/${alias.value}` }, collaboratorName: cname, collaborationInstruction: instr, relayConversationHistory: relay ? "TO_COLLABORATOR" : "DISABLED" });
              setCname(""); setInstr(""); cs.reload(); onChange(); notify.success("Collaborator added (re-prepare the agent)."); } catch (e) { notify.error(e); } }}>Add collaborator</Button></>}
      </SpaceBetween>
    </Container>
  );
}

function PromptPanel({ agent, onChange }) {
  const notify = useNotify();
  const [txt, setTxt] = useState(() => JSON.stringify(agent.promptOverrideConfiguration || { promptConfigurations: [{ promptType: "ORCHESTRATION", promptCreationMode: "OVERRIDDEN", promptState: "ENABLED", basePromptTemplate: "$instruction$\n\n$knowledge_base_guideline$\n$memory_guideline$", parserMode: "DEFAULT", inferenceConfiguration: { temperature: 0.4, maximumLength: 400 } }] }, null, 2));
  return (
    <ExpandableSection headerText="Advanced prompts (promptOverrideConfiguration)" variant="container">
      <SpaceBetween size="s">
        <Box variant="p">Override the pre-processing, orchestration, post-processing, routing and memory-summarisation prompts and point a parser Lambda at the model output. Placeholders: $instruction$, $question$, $knowledge_base_guideline$, $memory_content$, $conversation_history$, $agent_collaborators$, $latest_response$.</Box>
        <Textarea value={txt} rows={10} onChange={({ detail }) => setTxt(detail.value)} ariaLabel="Prompt override JSON" />
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={async () => { try { await api.updateAgent(agent.agentId, agent, { promptOverrideConfiguration: JSON.parse(txt) }); notify.success("Prompt configuration saved (re-prepare the agent)."); onChange(); } catch (e) { notify.error(e); } }}>Save</Button>
          {agent.promptOverrideConfiguration && <Button variant="link" onClick={async () => { try { await api.updateAgent(agent.agentId, agent, { promptOverrideConfiguration: null }); notify.success("Reset to default prompts."); onChange(); } catch (e) { notify.error(e); } }}>Reset to defaults</Button>}
        </SpaceBetween>
      </SpaceBetween>
    </ExpandableSection>
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
  const [trace, setTrace] = useState(true);
  const [lines, setLines] = useState([]);
  const [pending, setPending] = useState(null);
  const [rcText, setRcText] = useState("");
  const a = ag.data;
  const run = async (key, fn, ok) => { setBusy(key); try { await fn(); if (ok) notify.success(ok); ag.reload(); al.reload(); lk.reload(); } catch (e) { notify.error(e); } finally { setBusy(""); } };
  const handle = (r) => {
    if (r.traces?.length) setLines(traceLines(r.traces));
    if (r.returnControl) setPending(r.returnControl); else setPending(null);
    if (r.text || r.files?.length) setMsgs((m) => [...m, { r: "agent", t: r.text, c: r.citations.length, files: r.files }]);
  };
  const send = async () => {
    const text = input; setInput(""); setBusy("chat"); setMsgs((m) => [...m, { r: "user", t: text }]);
    try { handle(await api.invokeAgent(id, "TSTALIASID", session, text, { enableTrace: trace })); }
    catch (e) { setMsgs((m) => [...m, { r: "error", t: `${e.code}: ${e.message}` }]); } finally { setBusy(""); }
  };
  const answerRc = async (confirmationState) => {
    const inp = pending.invocationInputs[0]; const f = inp.functionInvocationInput, ap = inp.apiInvocationInput;
    const isConfirm = (f || ap).actionInvocationType === "CONFIRM";
    const res = f ? { functionResult: { actionGroup: f.actionGroup, function: f.function, ...(isConfirm ? { confirmationState } : {}), responseBody: { TEXT: { body: rcText || "done" } } } }
      : { apiResult: { actionGroup: ap.actionGroup, apiPath: ap.apiPath, httpMethod: ap.httpMethod, httpStatusCode: 200, ...(isConfirm ? { confirmationState } : {}), responseBody: { "application/json": { body: rcText || "done" } } } };
    setBusy("chat");
    try { handle(await api.invokeAgent(id, "TSTALIASID", session, "", { enableTrace: trace, sessionState: { invocationId: pending.invocationId, returnControlInvocationResults: [res] } })); setRcText(""); }
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
        {a && <ActionGroupsPanel agentId={id} onChange={ag.reload} />}
        {a && <CollaborationPanel agent={a} onChange={ag.reload} />}
        {a && <PromptPanel key={a.updatedAt} agent={a} onChange={ag.reload} />}
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
            <Checkbox checked={trace} onChange={({ detail }) => setTrace(detail.checked)}>Show trace</Checkbox>
            <div data-testid="chat" style={{ minHeight: 60 }}>{msgs.map((m, i) => <Box key={i} color={m.r === "error" ? "text-status-error" : "inherit"}><b>{m.r === "user" ? "You" : m.r === "agent" ? "Agent" : "Error"}:</b> {m.t}{m.c ? ` [${m.c} citation block]` : ""}{(m.files || []).map((f) => <span key={f.name}> [file: {f.name}]</span>)}</Box>)}</div>
            {pending && <Alert type="warning" header={(pending.invocationInputs[0].functionInvocationInput || pending.invocationInputs[0].apiInvocationInput).actionInvocationType === "CONFIRM" ? "The agent asks you to confirm an action" : "The agent returned control: run the action and reply with its result"}>
              <SpaceBetween size="xs"><Box variant="code">{JSON.stringify(pending.invocationInputs[0], null, 1)}</Box>
                {(pending.invocationInputs[0].functionInvocationInput || pending.invocationInputs[0].apiInvocationInput).actionInvocationType === "CONFIRM"
                  ? <SpaceBetween direction="horizontal" size="xs"><Button variant="primary" onClick={() => answerRc("CONFIRM")}>Confirm</Button><Button onClick={() => answerRc("DENY")}>Deny</Button></SpaceBetween>
                  : <SpaceBetween direction="horizontal" size="xs"><Input value={rcText} onChange={({ detail }) => setRcText(detail.value)} placeholder="Result of the action" ariaLabel="Action result" /><Button variant="primary" onClick={() => answerRc("")}>Send result</Button></SpaceBetween>}</SpaceBetween></Alert>}
            {trace && lines.length > 0 && <ExpandableSection headerText={`Trace (${lines.length} steps)`} defaultExpanded><Box variant="code"><div data-testid="trace" style={{ whiteSpace: "pre-wrap" }}>{lines.join("\n")}</div></Box></ExpandableSection>}
            <SpaceBetween direction="horizontal" size="xs"><Input value={input} onChange={({ detail }) => setInput(detail.value)} onKeyDown={({ detail }) => detail.key === "Enter" && input && send()} placeholder="Message the agent" ariaLabel="Message" /><Button variant="primary" loading={busy === "chat"} disabled={!input || a?.agentStatus !== "PREPARED"} onClick={send}>Send</Button></SpaceBetween>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
