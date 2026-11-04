/* Template studio — the template text editor + Validate are real (ValidateTemplate);
 * the visual resource Canvas is the declared gap (core/capabilities/aws/cloudformation.json:
 * aws.cloudformation.template-studio). "Save and continue" hands the template to
 * Create stack's file-upload step (sessionStorage is the simplest honest bridge — no
 * server-side "saved templates" store exists, so nothing claims to persist beyond this
 * browser tab). */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { useNotify } from "../../../common/notify.jsx";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import { ErrorAlert } from "../../kit/common.jsx";
import Canvas from "../../kit/Canvas.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

const DEFAULT_TEMPLATE = JSON.stringify({ AWSTemplateFormatVersion: "2010-09-09", Resources: {} }, null, 2);
const DESIGNER = "AWS::CloudFormation::Designer";

// Resource types the CloudFormation engine really provisions (core/cloudformation_core.py).
export const CFN_PALETTE = [
  { type: "AWS::S3::Bucket", idPrefix: "S3Bucket", label: "S3 Bucket", group: "Storage", color: "#037f0c", defaults: { props: '{\n  "VersioningConfiguration": { "Status": "Enabled" }\n}' } },
  { type: "AWS::DynamoDB::Table", idPrefix: "DynamoTable", label: "DynamoDB Table", group: "Database", color: "#0972d3",
    defaults: { props: '{\n  "BillingMode": "PAY_PER_REQUEST",\n  "AttributeDefinitions": [{ "AttributeName": "id", "AttributeType": "S" }],\n  "KeySchema": [{ "AttributeName": "id", "KeyType": "HASH" }]\n}' } },
  { type: "AWS::SQS::Queue", idPrefix: "Queue", label: "SQS Queue", group: "Application integration", color: "#b7791f", defaults: { props: "{}" } },
  { type: "AWS::SNS::Topic", idPrefix: "Topic", label: "SNS Topic", group: "Application integration", color: "#8456ce", defaults: { props: "{}" } },
  { type: "AWS::IAM::Role", idPrefix: "Role", label: "IAM Role", group: "Security", color: "#d91515",
    defaults: { props: '{\n  "AssumeRolePolicyDocument": { "Version": "2012-10-17", "Statement": [{ "Effect": "Allow", "Principal": { "Service": "lambda.amazonaws.com" }, "Action": "sts:AssumeRole" }] }\n}' } },
  { type: "AWS::Logs::LogGroup", idPrefix: "LogGroup", label: "Logs LogGroup", group: "Management", color: "#0f766e", defaults: { props: "{}" } },
];

const refsIn = (v, out = new Set()) => {
  if (Array.isArray(v)) v.forEach((x) => refsIn(x, out));
  else if (v && typeof v === "object") {
    for (const [k, x] of Object.entries(v)) {
      if (k === "Ref" && typeof x === "string") out.add(x);
      else if (k === "Fn::GetAtt") out.add(String(Array.isArray(x) ? x[0] : x).split(".")[0]);
      else if (k === "Fn::Sub" && typeof (Array.isArray(x) ? x[0] : x) === "string") [...(Array.isArray(x) ? x[0] : x).matchAll(/\$\{([A-Za-z0-9]+)/g)].forEach((m) => out.add(m[1]));
      else refsIn(x, out);
    }
  }
  return out;
};

/** template text -> graph (positions preserved by logical id, then Designer metadata, then a grid). */
export function templateToGraph(text, prevNodes = []) {
  const t = JSON.parse(text || "{}");
  const res = t.Resources || {};
  const designer = t.Metadata?.[DESIGNER] || {};
  const ids = Object.keys(res);
  const nodes = ids.map((id, i) => {
    const prev = prevNodes.find((n) => n.id === id), pos = designer[id]?.position;
    const { Type, Properties, DependsOn, ...rest } = res[id] || {};
    return { id, type: Type || "Unknown", label: id, x: prev?.x ?? pos?.x ?? 24 + (i % 3) * 220, y: prev?.y ?? pos?.y ?? 24 + Math.floor(i / 3) * 90,
      data: { props: JSON.stringify(Properties || {}, null, 2), extra: rest } };
  });
  const edges = []; const seen = new Set();
  ids.forEach((id) => {
    const deps = new Set([].concat(res[id]?.DependsOn || []));
    refsIn(res[id]?.Properties).forEach((r) => { if (res[r] && r !== id) deps.add(r); });
    deps.forEach((d) => { if (res[d] && !seen.has(`${d}>${id}`)) { seen.add(`${d}>${id}`); edges.push({ id: `e-${d}-${id}`, from: d, to: id }); } });
  });
  return { nodes, edges };
}

/** graph -> template text, merging into the existing template so Parameters/Outputs/etc. survive. */
export function graphToTemplate(graph, baseText) {
  let base = {};
  try { base = JSON.parse(baseText || "{}"); } catch { base = {}; }
  const resources = {}; const designer = {};
  graph.nodes.forEach((n) => {
    let props = {}; try { props = JSON.parse(n.data?.props || "{}"); } catch { props = n.data?.badProps ?? {}; }
    const deps = graph.edges.filter((e) => e.to === n.id).map((e) => e.from);
    const own = [].concat(base.Resources?.[n.id]?.DependsOn || []).filter((d) => graph.nodes.some((x) => x.id === d));
    const all = [...new Set([...own, ...deps])];
    resources[n.id] = { Type: n.type, ...(Object.keys(props).length ? { Properties: props } : {}), ...(all.length ? { DependsOn: all.length === 1 ? all[0] : all } : {}), ...(n.data?.extra || {}) };
    designer[n.id] = { position: { x: Math.round(n.x), y: Math.round(n.y) } };
  });
  const out = { AWSTemplateFormatVersion: "2010-09-09", ...base, Resources: resources, Metadata: { ...(base.Metadata || {}), [DESIGNER]: designer } };
  return JSON.stringify(out, null, 2);
}

const isJson = (s) => { try { JSON.parse(s); return true; } catch { return false; } };

export default function TemplateStudio() {
  const notify = useNotify();
  const [view, setView] = useState("Both");
  const [format, setFormat] = useState({ value: "JSON", label: "JSON" });
  const [text, setText] = useState(() => { try { return sessionStorage.getItem("vyomi-cfn-studio") || DEFAULT_TEMPLATE; } catch { return DEFAULT_TEMPLATE; } });
  const [graph, setGraph] = useState(() => { try { return templateToGraph(text); } catch { return { nodes: [], edges: [] }; } });
  const [selected, setSelected] = useState(null);
  const [deploy, setDeploy] = useState(false);
  const [stackName, setStackName] = useState("");
  const jsonOk = isJson(text);

  const onText = (v) => {
    setText(v);
    try { sessionStorage.setItem("vyomi-cfn-studio", v); } catch { /* ignore */ }
    if (isJson(v)) { try { setGraph((g) => templateToGraph(v, g.nodes)); } catch { /* keep graph */ } }
  };
  const onCanvas = (g) => { setGraph(g); onText(graphToTemplate(g, text)); };
  const startFresh = () => { onText(DEFAULT_TEMPLATE); setGraph({ nodes: [], edges: [] }); };
  const doDeploy = async () => {
    setBusy(true); setError(null);
    try {
      await api.createStack({ name: stackName, templateBody: text, capabilities: ["CAPABILITY_NAMED_IAM"] });
      notify.success(`Stack ${stackName} creation started from the canvas.`);
      setDeploy(false); navigate("cloudformation", "stacks");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const validate = async () => {
    setBusy(true); setError(null); setResult(null);
    try { const r = await api.validateTemplate(text); setResult(r); notify.success("Template is valid."); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button loading={busy} onClick={validate}>Validate</Button>
          <Button disabled={!jsonOk} onClick={() => setDeploy(true)}>Create stack from template</Button>
          <Button variant="primary" onClick={() => { sessionStorage.setItem("vyomi-cfn-template", text); notify.success("Template saved for this browser session — paste it in Create stack's file upload step."); }}>Save and continue</Button>
        </SpaceBetween>
      }>Template studio</Header>
    }>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<ButtonDropdown items={[{ id: "clear", text: "Clear template" }]}
          onItemClick={({ detail }) => { if (detail.id === "clear") startFresh(); }}>Actions</ButtonDropdown>}>Template</Header>}>
          <SpaceBetween size="l">
            <SpaceBetween direction="horizontal" size="l">
              <FormField label="View">
                <RadioGroup value={view} onChange={({ detail }) => setView(detail.value)} items={[
                  { value: "Template", label: "Template" }, { value: "Canvas", label: "Canvas" }, { value: "Both", label: "Both" },
                ]} />
              </FormField>
              <FormField label="Format">
                <Select selectedOption={format} onChange={({ detail }) => setFormat(detail.selectedOption)}
                  options={[{ value: "JSON", label: "JSON" }]} />
              </FormField>
            </SpaceBetween>
            <SpaceBetween size="l">
              {view !== "Canvas" && (
                <Box>
                  <FormField label="Template editor" stretch>
                    <Textarea rows={18} value={text} onChange={({ detail }) => onText(detail.value)} spellcheck={false} ariaLabel="Template editor" />
                  </FormField>
                </Box>
              )}
            </SpaceBetween>
            {view !== "Template" && (
              <CapabilityContainer id="aws.cloudformation.template-studio" title="Canvas">
                {jsonOk ? (
                  <Canvas ariaLabel="Template canvas" palette={CFN_PALETTE} nodes={graph.nodes} edges={graph.edges} onChange={onCanvas}
                    selectedId={selected} onSelect={setSelected}
                    canConnect={(a, b) => (graph.edges.some((e) => e.from === b.id && e.to === a.id) ? "That would create a circular dependency." : true)}
                    renderInspector={(n, patch) => (
                      <SpaceBetween size="s">
                        <FormField label="Logical ID" description="Alphanumeric; renaming does not rewrite Ref expressions.">
                          <Input value={n.label} ariaLabel="Logical ID" onChange={({ detail }) => {
                            const id = detail.value.replace(/[^A-Za-z0-9]/g, "");
                            if (!id || graph.nodes.some((x) => x.id === id && x.id !== n.id)) return;
                            const g = { nodes: graph.nodes.map((x) => (x.id === n.id ? { ...x, id, label: id } : x)),
                              edges: graph.edges.map((e) => ({ ...e, from: e.from === n.id ? id : e.from, to: e.to === n.id ? id : e.to })) };
                            setSelected(id); onCanvas(g);
                          }} />
                        </FormField>
                        <FormField label="Type"><Box>{n.type}</Box></FormField>
                        <FormField label="Properties (JSON)" errorText={isJson(n.data?.props || "{}") ? null : "Properties must be valid JSON."}>
                          <Textarea rows={9} ariaLabel="Resource properties" value={n.data?.props || "{}"} onChange={({ detail }) => patch({ data: { props: detail.value } })} spellcheck={false} />
                        </FormField>
                      </SpaceBetween>
                    )} />
                ) : (
                  <SpaceBetween size="s">
                    <Box color="text-status-warning">The editor does not contain a JSON template, so the canvas cannot read it. Fix the JSON, or start a new canvas template (replaces the editor text).</Box>
                    <Button onClick={startFresh}>Start a new canvas template</Button>
                  </SpaceBetween>
                )}
              </CapabilityContainer>
            )}
            {error && <ErrorAlert error={error} header="Template is invalid" />}
            {result && (
              <Box variant="code">
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(result, null, 2)}</pre>
              </Box>
            )}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
      <Modal visible={deploy} onDismiss={() => setDeploy(false)} header="Create stack from this template"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setDeploy(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!/^[A-Za-z][-A-Za-z0-9]{0,127}$/.test(stackName)} onClick={doDeploy}>Create stack</Button></SpaceBetween></Box>}>
        <FormField label="Stack name"><Input value={stackName} ariaLabel="Stack name" onChange={({ detail }) => setStackName(detail.value)} /></FormField>
      </Modal>
    </ContentLayout>
  );
}
