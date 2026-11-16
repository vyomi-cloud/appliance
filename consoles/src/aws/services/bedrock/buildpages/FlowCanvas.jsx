/* Visual flow builder for Bedrock Flows: drag nodes from the palette onto an xyflow (React Flow, MIT) canvas, wire output handles to input
 * handles, edit node configuration in the side panel. The graph state is the source of truth; toDefinition() produces the real
 * CreateFlow/UpdateFlow `definition` (nodes + Data/Conditional connections), fromDefinition() reads one back. Node positions are UI-only
 * and kept in localStorage per flow (the Bedrock definition has no layout). Shared by AWS Flows and the Azure Foundry prompt-flow editor. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, ReactFlowProvider, Background, Controls, Handle, MarkerType, Position, addEdge, applyEdgeChanges, applyNodeChanges, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Textarea from "@cloudscape-design/components/textarea";

/** Node catalogue: inputs/outputs are the real Bedrock Flows node ports. `fixed` ports cannot be edited; Prompt/Condition ports are dynamic. */
export const NODE_TYPES = {
  Input: { color: "#037f0c", inputs: [], outputs: ["document"], cfg: () => ({ input: {} }), help: "Flow entry point (exactly one)." },
  Output: { color: "#d13212", inputs: ["document"], outputs: [], cfg: () => ({ output: {} }), help: "Returns a value to the caller (flowOutputEvent)." },
  Prompt: { color: "#0972d3", inputs: ["input"], outputs: ["modelCompletion"], dynamicInputs: true, help: "Runs a prompt template on a model.", cfg: (o) => ({ prompt: { sourceConfiguration: { inline: { modelId: o.modelId || "", templateType: "TEXT", templateConfiguration: { text: { text: "{{input}}", inputVariables: [{ name: "input" }] } }, inferenceConfiguration: { text: { temperature: 0.2 } } } } } }) },
  Condition: { color: "#8c4fff", inputs: ["input"], outputs: [], dynamicInputs: true, conditions: true, help: "Branches on expressions: name == \"x\", !=, contains, > < >= <=, and / or, default.", cfg: () => ({ condition: { conditions: [{ name: "case1", expression: "input == \"yes\"" }, { name: "default", expression: "default" }] } }) },
  Iterator: { color: "#c33d69", inputs: ["array"], outputs: ["arrayItem", "arraySize"], help: "Fans an array out: downstream nodes run once per item.", cfg: () => ({ iterator: {} }) },
  Collector: { color: "#c33d69", inputs: ["arrayItem"], outputs: ["collectedArray"], help: "Joins the per-item results back into an ordered array.", cfg: () => ({ collector: {} }) },
  Agent: { color: "#d97706", inputs: ["agentInputText"], outputs: ["agentResponse"], help: "Invokes a Bedrock agent alias.", cfg: () => ({ agent: { agentAliasArn: "" } }) },
  KnowledgeBase: { color: "#0e7490", inputs: ["retrievalQuery"], outputs: ["outputText"], help: "Queries a knowledge base; with a model it generates a grounded answer, without it returns the retrieved chunks.", cfg: () => ({ knowledgeBase: { knowledgeBaseId: "" } }) },
  LambdaFunction: { color: "#b45309", inputs: ["codeHookInput"], outputs: ["functionResponse"], help: "Invokes a Lambda function with the input as the event.", cfg: () => ({ lambdaFunction: { lambdaArn: "" } }) },
  Retrieval: { color: "#2563eb", inputs: ["objectKey"], outputs: ["s3Content"], help: "Reads an object from S3.", cfg: () => ({ retrieval: { serviceConfiguration: { s3: { bucketName: "" } } } }) },
  Storage: { color: "#2563eb", inputs: ["content", "objectKey"], outputs: ["s3Uri"], help: "Writes an object to S3.", cfg: () => ({ storage: { serviceConfiguration: { s3: { bucketName: "" } } } }) },
  Loop: { color: "#7c3aed", inputs: ["loopInput"], outputs: ["loopOutput"], help: "Repeats a body until its LoopController condition is false (max iterations).", cfg: () => ({ loop: { definition: LOOP_BODY() } }) },
};
const LOOP_BODY = () => ({
  nodes: [
    { name: "LoopInput", type: "LoopInput", configuration: { loopInput: {} }, outputs: [{ name: "loopInput", type: "String" }] },
    { name: "LoopController", type: "LoopController", configuration: { loopController: { continueCondition: { name: "again", expression: "input < 3" }, maxIterations: 5 } }, inputs: [{ name: "input", type: "String", expression: "$.data" }] },
  ],
  connections: [{ name: "LoopInputToLoopController", type: "Data", source: "LoopInput", target: "LoopController", configuration: { data: { sourceOutput: "loopInput", targetInput: "input" } } }],
});
const CFG_KEY = { Input: "input", Output: "output", Prompt: "prompt", Condition: "condition", Iterator: "iterator", Collector: "collector", Agent: "agent", KnowledgeBase: "knowledgeBase", LambdaFunction: "lambdaFunction", Retrieval: "retrieval", Storage: "storage", Loop: "loop" };
const PALETTE = ["Prompt", "Condition", "Agent", "KnowledgeBase", "LambdaFunction", "Iterator", "Collector", "Loop", "Retrieval", "Storage", "Output"];

const plist = (names) => names.map((n) => ({ name: n, type: "String", ...({ expression: "$.data" }) }));
const varsOf = (t) => [...new Set([...String(t || "").matchAll(/\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g)].map((m) => m[1]))];

/** definition -> {nodes, edges} for xyflow (auto layout by depth unless positions are known). */
export function fromDefinition(def, layout = {}) {
  const ns = def?.nodes || [], cs = def?.connections || [];
  const depth = {};
  const incoming = (n) => cs.filter((c) => c.target === n);
  const d = (n, seen = new Set()) => { if (depth[n] != null) return depth[n]; if (seen.has(n)) return 0; seen.add(n); depth[n] = Math.max(-1, ...incoming(n).map((c) => d(c.source, seen))) + 1; return depth[n]; };
  ns.forEach((n) => d(n.name));
  const rows = {};
  const nodes = ns.map((n) => {
    const spec = NODE_TYPES[n.type] || { inputs: [], outputs: [], color: "#687078" };
    const col = depth[n.name] || 0;
    rows[col] = (rows[col] ?? -1) + 1;
    const conds = n.type === "Condition" ? ((n.configuration?.condition?.conditions) || []).map((c) => c.name) : null;
    return {
      id: n.name, type: "flowNode", position: layout[n.name] || { x: col * 280, y: rows[col] * 170 },
      data: { name: n.name, type: n.type, configuration: n.configuration || {}, inputs: (n.inputs || []).map((i) => i.name).length ? n.inputs.map((i) => i.name) : spec.inputs, outputs: conds ? conds : ((n.outputs || []).map((o) => o.name).length ? n.outputs.map((o) => o.name) : spec.outputs) },
    };
  });
  const edges = cs.map((c) => {
    const cond = c.type === "Conditional";
    const dd = c.configuration?.data || {};
    return {
      id: c.name, source: c.source, target: c.target, sourceHandle: cond ? c.configuration?.conditional?.condition : dd.sourceOutput, targetHandle: cond ? (nodes.find((x) => x.id === c.target)?.data.inputs[0] || "in") : dd.targetInput,
      markerEnd: { type: MarkerType.ArrowClosed }, data: { kind: cond ? "Conditional" : "Data" }, ...(cond ? { style: { strokeDasharray: "5 4" }, label: c.configuration?.conditional?.condition } : {}),
    };
  });
  return { nodes, edges };
}

/** xyflow graph -> Bedrock Flows definition. */
export function toDefinition(nodes, edges) {
  const ns = nodes.map((n) => {
    const { name, type, configuration, inputs, outputs } = n.data;
    return { name, type, configuration, ...(inputs.length ? { inputs: plist(inputs) } : {}), ...(type !== "Condition" && outputs.length ? { outputs: outputs.map((o) => ({ name: o, type: "String" })) } : {}) };
  });
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const cs = edges.map((e) => {
    const src = byId[e.source]?.data, tgt = byId[e.target]?.data;
    if (src?.type === "Condition") return { name: `${e.source}_${e.sourceHandle}_To_${e.target}`.replace(/[^A-Za-z0-9_]/g, ""), type: "Conditional", source: e.source, target: e.target, configuration: { conditional: { condition: e.sourceHandle } } };
    return { name: `${e.source}${e.sourceHandle}To${e.target}${e.targetHandle}`.replace(/[^A-Za-z0-9_]/g, ""), type: "Data", source: e.source, target: e.target, configuration: { data: { sourceOutput: e.sourceHandle, targetInput: e.targetHandle } } };
  });
  return { nodes: ns, connections: cs };
}

function FlowNode({ data, selected }) {
  const spec = NODE_TYPES[data.type] || { color: "#687078" };
  const st = data.runState;   // "ok" | "error" | undefined
  const border = st === "ok" ? "#037f0c" : st === "error" ? "#d13212" : selected ? "#0972d3" : spec.color;
  const rows = Math.max(data.inputs.length, data.outputs.length, 1);
  return (
    <div data-testid={`flownode-${data.name}`} style={{ minWidth: 190, background: "#fff", color: "#0f1b2a", border: `2px solid ${border}`, borderRadius: 8, boxShadow: selected ? "0 0 0 3px rgba(9,114,211,.25)" : "0 1px 3px rgba(0,0,0,.2)", fontSize: 12 }}>
      <div style={{ background: spec.color, color: "#fff", padding: "4px 10px", borderRadius: "5px 5px 0 0", fontWeight: 700, display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span>{data.name}</span><span style={{ opacity: 0.85, fontWeight: 400 }}>{data.type}{st === "ok" ? " ✓" : st === "error" ? " !" : ""}</span>
      </div>
      <div style={{ position: "relative", height: rows * 24 + 8 }}>
        {data.inputs.map((n, i) => (<div key={`i${n}`} style={{ position: "absolute", left: 12, top: 6 + i * 24, lineHeight: "18px" }}>{n}<Handle type="target" id={n} position={Position.Left} style={{ top: 15 + i * 24, left: -7, width: 10, height: 10, background: "#0972d3" }} /></div>))}
        {data.outputs.map((n, i) => (<div key={`o${n}`} style={{ position: "absolute", right: 12, top: 6 + i * 24, lineHeight: "18px", textAlign: "right" }}>{n}<Handle type="source" id={n} position={Position.Right} style={{ top: 15 + i * 24, right: -7, width: 10, height: 10, background: data.type === "Condition" ? "#8c4fff" : "#037f0c" }} /></div>))}
      </div>
    </div>
  );
}
const nodeTypes = { flowNode: FlowNode };
const uniqueName = (nodes, base) => { let n = base, i = 1; const used = new Set(nodes.map((x) => x.id)); while (used.has(n)) n = `${base}_${++i}`; return n; };

function ConfigPanel({ node, update, rename, remove, opts }) {
  const d = node.data;
  const set = (patch) => update(node.id, patch);
  const cfg = d.configuration || {};
  const key = CFG_KEY[d.type];
  const setCfg = (inner) => set({ configuration: { ...cfg, [key]: inner } });
  const inline = cfg.prompt?.sourceConfiguration?.inline;
  const field = (label, value, onChange, ph) => <FormField label={label}><Input value={value || ""} onChange={({ detail }) => onChange(detail.value)} placeholder={ph} ariaLabel={label} /></FormField>;
  const pick = (label, value, items, onChange, ph) => (
    <FormField label={label}>
      <select aria-label={label} value={items.some((i) => i.value === value) ? value : ""} onChange={(e) => onChange(e.target.value)} style={{ width: "100%", padding: 6 }}>
        <option value="">{ph}</option>{items.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
      </select>
    </FormField>
  );
  return (
    <SpaceBetween size="s" data-testid="node-config">
      <Box variant="h3">{d.type} node</Box>
      <Box color="text-body-secondary" variant="small">{(NODE_TYPES[d.type] || {}).help}</Box>
      {field("Node name", d.name, (v) => rename(node.id, v.replace(/[^A-Za-z0-9_]/g, "")))}
      {d.type === "Prompt" && inline && (<>
        {pick("Model", inline.modelId, opts.models, (v) => setCfg({ ...cfg.prompt, sourceConfiguration: { inline: { ...inline, modelId: v } } }), "Choose a model")}
        <FormField label="Prompt template" description="{{variables}} become the node's input ports."><Textarea rows={5} value={inline.templateConfiguration?.text?.text || ""} ariaLabel="Prompt template"
          onChange={({ detail }) => { const vs = varsOf(detail.value); setCfg({ ...cfg.prompt, sourceConfiguration: { inline: { ...inline, templateConfiguration: { text: { text: detail.value, inputVariables: vs.map((n) => ({ name: n })) } } } } }); set({ inputs: vs.length ? vs : ["input"] }); }} /></FormField>
      </>)}
      {d.type === "Prompt" && !inline && <Box variant="small">This prompt node uses a Prompt Management resource ({cfg.prompt?.sourceConfiguration?.resource?.promptArn}).</Box>}
      {d.type === "Condition" && (<SpaceBetween size="xs">
        <Box variant="awsui-key-label">Conditions (each becomes an output port)</Box>
        {(cfg.condition?.conditions || []).map((c, i) => (<SpaceBetween key={i} direction="horizontal" size="xs">
          <Input value={c.name} ariaLabel={`condition ${i} name`} onChange={({ detail }) => { const cs = cfg.condition.conditions.map((x, j) => (j === i ? { ...x, name: detail.value.replace(/[^A-Za-z0-9_]/g, "") } : x)); setCfg({ conditions: cs }); set({ outputs: cs.map((x) => x.name) }); }} />
          <Input value={c.expression} ariaLabel={`condition ${i} expression`} onChange={({ detail }) => setCfg({ conditions: cfg.condition.conditions.map((x, j) => (j === i ? { ...x, expression: detail.value } : x)) })} />
          <Button iconName="close" variant="icon" ariaLabel="Remove condition" onClick={() => { const cs = cfg.condition.conditions.filter((_, j) => j !== i); setCfg({ conditions: cs }); set({ outputs: cs.map((x) => x.name) }); }} />
        </SpaceBetween>))}
        <Button onClick={() => { const cs = [...(cfg.condition?.conditions || []), { name: `case${(cfg.condition?.conditions || []).length + 1}`, expression: "input == \"\"" }]; setCfg({ conditions: cs }); set({ outputs: cs.map((x) => x.name) }); }}>Add condition</Button>
        {field("Input ports (comma separated)", d.inputs.join(","), (v) => set({ inputs: v.split(",").map((s) => s.trim()).filter(Boolean) }))}
      </SpaceBetween>)}
      {d.type === "Agent" && pick("Agent alias", cfg.agent?.agentAliasArn, opts.aliases, (v) => setCfg({ agentAliasArn: v }), "Choose an agent alias")}
      {d.type === "KnowledgeBase" && (<>
        {pick("Knowledge base", cfg.knowledgeBase?.knowledgeBaseId, opts.kbs, (v) => setCfg({ ...cfg.knowledgeBase, knowledgeBaseId: v }), "Choose a knowledge base")}
        {pick("Generate with model (optional)", cfg.knowledgeBase?.modelId, opts.models, (v) => { const k = { ...cfg.knowledgeBase }; if (v) k.modelId = v; else delete k.modelId; setCfg(k); }, "None: return retrieved chunks")}
      </>)}
      {d.type === "LambdaFunction" && pick("Function", cfg.lambdaFunction?.lambdaArn, opts.lambdas, (v) => setCfg({ lambdaArn: v }), "Choose a function")}
      {(d.type === "Retrieval" || d.type === "Storage") && pick("S3 bucket", cfg[key]?.serviceConfiguration?.s3?.bucketName, opts.buckets, (v) => setCfg({ serviceConfiguration: { s3: { bucketName: v } } }), "Choose a bucket")}
      {d.type === "Loop" && (<>
        <FormField label="Continue while (LoopController)" description='Evaluated on the controller input, e.g. input < 3'>
          <Input ariaLabel="Loop condition" value={cfg.loop?.definition?.nodes?.find((n) => n.type === "LoopController")?.configuration?.loopController?.continueCondition?.expression || ""}
            onChange={({ detail }) => setCfg({ definition: { ...cfg.loop.definition, nodes: cfg.loop.definition.nodes.map((n) => (n.type === "LoopController" ? { ...n, configuration: { loopController: { ...n.configuration.loopController, continueCondition: { name: "again", expression: detail.value } } } } : n)) } })} />
        </FormField>
        <FormField label="Max iterations"><Input type="number" ariaLabel="Max iterations" value={String(cfg.loop?.definition?.nodes?.find((n) => n.type === "LoopController")?.configuration?.loopController?.maxIterations ?? 5)}
          onChange={({ detail }) => setCfg({ definition: { ...cfg.loop.definition, nodes: cfg.loop.definition.nodes.map((n) => (n.type === "LoopController" ? { ...n, configuration: { loopController: { ...n.configuration.loopController, maxIterations: Number(detail.value) || 1 } } } : n)) } })} /></FormField>
        <FormField label="Loop body (JSON)" description="Nodes between LoopInput and LoopController; the controller's `input` is fed back into the next iteration."><Textarea rows={8} ariaLabel="Loop body" value={JSON.stringify(cfg.loop?.definition, null, 1)} onChange={({ detail }) => { try { setCfg({ definition: JSON.parse(detail.value) }); } catch { /* keep typing */ } }} /></FormField>
      </>)}
      {d.type !== "Input" && <Button onClick={() => remove(node.id)}>Delete node</Button>}
    </SpaceBetween>
  );
}

function Canvas({ initial, onChange, layoutKey, opts, runStates, height = 480, extraPalette = [] }) {
  const [nodes, setNodes] = useState(() => fromDefinition(initial, readLayout(layoutKey)).nodes);
  const [edges, setEdges] = useState(() => fromDefinition(initial, readLayout(layoutKey)).edges);
  const [selId, setSelId] = useState(null);
  const wrap = useRef(null);
  const rf = useReactFlow();
  const sig = useRef("");
  useEffect(() => { const def = toDefinition(nodes, edges); const s = JSON.stringify(def); if (s !== sig.current) { sig.current = s; onChange(def); } }, [nodes, edges]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem(layoutKey, JSON.stringify(Object.fromEntries(nodes.map((n) => [n.id, n.position])))); } catch { /* private mode */ } }, [nodes, layoutKey]);
  const shown = useMemo(() => nodes.map((n) => ({ ...n, data: { ...n.data, runState: runStates?.[n.id] } })), [nodes, runStates]);
  const onNodesChange = useCallback((ch) => setNodes((ns) => applyNodeChanges(ch, ns)), []);
  const onEdgesChange = useCallback((ch) => setEdges((es) => applyEdgeChanges(ch, es)), []);
  const onConnect = useCallback((c) => setEdges((es) => {
    if (c.source === c.target) return es;
    const cond = nodes.find((n) => n.id === c.source)?.data.type === "Condition";
    const dup = es.find((e) => e.source === c.source && e.sourceHandle === c.sourceHandle && e.target === c.target && e.targetHandle === c.targetHandle);
    if (dup) return es;
    return addEdge({ ...c, id: `e${Date.now().toString(36)}${es.length}`, markerEnd: { type: MarkerType.ArrowClosed }, data: { kind: cond ? "Conditional" : "Data" }, ...(cond ? { style: { strokeDasharray: "5 4" }, label: c.sourceHandle } : {}) }, es);
  }), [nodes]);
  const addNode = (type, position) => {
    const spec = NODE_TYPES[type];
    const name = uniqueName(nodes, type === "Output" ? "FlowOutputNode" : type);
    const conds = type === "Condition";
    const configuration = spec.cfg({ modelId: opts.models[0]?.value });
    const n = { id: name, type: "flowNode", position, data: { name, type, configuration, inputs: spec.inputs, outputs: conds ? ["case1", "default"] : spec.outputs } };
    setNodes((ns) => [...ns.map((x) => ({ ...x, selected: false })), { ...n, selected: true }]);
    setSelId(name);
  };
  const onDrop = (e) => {
    e.preventDefault();
    const t = e.dataTransfer.getData("application/vyomi-flow-node");
    if (t) addNode(t, rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };
  const update = (id, patch) => setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));
  const rename = (id, nm) => {
    if (!nm || (nm !== id && nodes.some((n) => n.id === nm))) return;
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, id: nm, data: { ...n.data, name: nm } } : n)));
    setEdges((es) => es.map((e) => ({ ...e, source: e.source === id ? nm : e.source, target: e.target === id ? nm : e.target })));
    setSelId(nm);
  };
  const remove = (id) => { setNodes((ns) => ns.filter((n) => n.id !== id)); setEdges((es) => es.filter((e) => e.source !== id && e.target !== id)); setSelId(null); };
  const sel = nodes.find((n) => n.id === selId);
  const relayout = () => { const g = fromDefinition(toDefinition(nodes, edges)); setNodes(g.nodes.map((n) => ({ ...n, selected: n.id === selId }))); setTimeout(() => rf.fitView({ padding: 0.15 }), 30); };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "150px 1fr 290px", gap: 12, alignItems: "start" }} data-testid="flow-builder">
      <div data-testid="flow-palette">
        <Box variant="awsui-key-label">Drag onto the canvas</Box>
        <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
          {[...PALETTE, ...extraPalette].map((t) => (
            <div key={t} draggable onDragStart={(e) => { e.dataTransfer.setData("application/vyomi-flow-node", t); e.dataTransfer.effectAllowed = "move"; }} onClick={() => addNode(t, { x: 80 + nodes.length * 24, y: 60 + nodes.length * 24 })} data-testid={`palette-${t}`}
              title={`${NODE_TYPES[t].help} (click to add)`} style={{ cursor: "grab", border: `1px solid ${NODE_TYPES[t].color}`, borderLeft: `5px solid ${NODE_TYPES[t].color}`, borderRadius: 4, padding: "5px 8px", fontSize: 12, background: "var(--color-background-container-content, #fff)" }}>{t}</div>
          ))}
        </div>
        <div style={{ marginTop: 10 }}><Button onClick={relayout}>Auto layout</Button></div>
      </div>
      <div ref={wrap} style={{ height, border: "1px solid #aab7b8", borderRadius: 6, background: "#f7f8fa" }} data-testid="flow-canvas" onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }} onDrop={onDrop}>
        <ReactFlow nodes={shown} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onNodeClick={(_, n) => setSelId(n.id)} onPaneClick={() => setSelId(null)}
          fitView fitViewOptions={{ padding: 0.2, maxZoom: 1 }} deleteKeyCode={["Backspace", "Delete"]} proOptions={{ hideAttribution: true }}>
          <Background gap={16} /><Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div>{sel ? <ConfigPanel node={sel} update={update} rename={rename} remove={remove} opts={opts} /> : <Box color="text-body-secondary" variant="small">Select a node to edit it. Connect an output port (right) to an input port (left) to pass a value; edges from a Condition port are conditional branches.</Box>}</div>
    </div>
  );
}
const readLayout = (k) => { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } };

/** Props: definition (initial), onChange(definition), layoutKey, opts {models, aliases, kbs, lambdas, buckets}, runStates {nodeName: ok|error}. Remount (key) to load a new definition. */
export default function FlowCanvas(props) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}
