/* Cloud-neutral infrastructure diagram (React Flow / xyflow, MIT). Every stack follows one layer template, left to right:
 *   1 users & external apps -> 2 gateway / firewall / proxy / load balancing -> 3 services & serverless -> 4 database / NoSQL / storage
 * and every layer is split into INBOUND (how traffic, events or access get in), CORE (what does the layer's job) and OUTBOUND (what it may
 * call or depends on). Layers 2-4 sit in a wrapper (AWS: Region > VPC, Azure: Resource group > Virtual network). Supporting resources
 * (IAM, logs, secrets, subnets...) join the layer of the resources they serve, found from the dependency edges.
 * A cloud plugs in through a `profile` (type -> layer / role rules, icons, entry points). Drag, zoom, pan, minimap. */
import { useEffect, useMemo } from "react";
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ServiceIcon from "../icons/ServiceIcon.jsx";

const NW = 132, NH = 96, PAD = 28, HEAD = 34;
const RING = { supported: "#1d8102", planned: "#b7791f", not_possible: "#d13212" };
const DASH = { supported: "solid", planned: "dashed", not_possible: "dotted" };
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

function ResourceNode({ data }) {
  return (
    <div title={`${data.type}${data.reason ? " - " + data.reason : ""}`} style={{ width: NW, textAlign: "center", opacity: data.dim ? 0.35 : 1 }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ width: 52, height: 52, margin: "0 auto", borderRadius: 10, padding: 4, background: "#fff", boxSizing: "border-box",
        border: `2px ${DASH[data.status]} ${RING[data.status]}`, boxShadow: data.selected ? "0 0 0 3px #0972d340" : "none" }}>
        {data.Icon ? <data.Icon style={{ fontSize: 34, color: "#1a73e8" }} /> : <ServiceIcon cloud={data.cloud || "aws"} id={data.icon} size={40} />}
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#16191f", marginTop: 4, lineHeight: "14px" }}>{clip(data.label, 20)}</div>
      <div style={{ fontSize: 10.5, color: "#5f6b7a", lineHeight: "13px" }}>{clip(data.typeLabel || data.type, 24)}</div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}
const GROUP_STYLE = {
  region: { border: "2px dashed #7a8699", bg: "#ffffff80", color: "#414d5c", icon: null },
  vpc: { border: "2px solid #8c4fff", bg: "#8c4fff0d", color: "#6b2fd9", icon: "vpc" },
  layer: { border: "1.5px dashed #9aa3b2", bg: "#ffffffb3", color: "#414d5c", icon: null },
  sub: { border: "1px dotted #c3cad5", bg: "#f6f8fa", color: "#6b7787", icon: null },
};
function GroupNode({ data }) {
  const g = GROUP_STYLE[data.kind] || GROUP_STYLE.layer;
  return (
    <div style={{ width: "100%", height: "100%", border: g.border, borderRadius: 10, background: g.bg, boxSizing: "border-box", position: "relative" }}>
      <div style={{ position: "absolute", top: 7, left: 10, display: "flex", alignItems: "center", gap: 6, fontSize: data.kind === "layer" ? 11.5 : data.kind === "sub" ? 10.5 : 12.5, fontWeight: 700, color: g.color }}>
        {data.kind === "vpc" && data.icon && <ServiceIcon cloud={data.cloud || "aws"} id={data.icon} size={18} />}{data.label}{data.cidr ? <span style={{ fontWeight: 400, color: "#5f6b7a" }}>{data.cidr}</span> : null}
      </div>
      {data.empty && <div style={{ position: "absolute", top: "50%", left: 0, right: 0, textAlign: "center", fontSize: 11, color: "#aab2bf" }}>none</div>}
    </div>
  );
}
function ExternalNode({ data }) {
  return (
    <div style={{ width: NW, textAlign: "center" }}>
      <div style={{ width: 52, height: 52, margin: "0 auto", borderRadius: 26, background: "#fff", border: "2px solid #5f6b7a", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }} aria-hidden>🌐</div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#16191f", marginTop: 4, lineHeight: "14px" }}>{data.label}</div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}
const nodeTypes = { resource: ResourceNode, group: GroupNode, external: ExternalNode };

const ROLES = [["inbound", "Inbound"], ["core", "Core"], ["outbound", "Outbound"]];
const GAP = 12, PER_COL = 6, EMPTY_W = 84, SUBHEAD = 22;
const DEFAULT_TITLES = { external: "1 · Users & external apps", edge: "2 · Gateway, firewall, proxy & load balancing", compute: "3 · Services & serverless", data: "4 · Database, NoSQL & storage" };
const roleOf = (p, type) => (p.inbound.test(type) ? "inbound" : p.outbound.test(type) ? "outbound" : "core");

/** Layer of every node: by type, else the layer most of its neighbours are in, else a type fallback, else services. */
export function assignLayers(nodes, edges, p) {
  const layer = {};
  nodes.forEach((n) => { const r = p.primary.find(([, re]) => re.test(n.type)); if (r) layer[n.id] = r[0]; });
  const adj = {}; edges.forEach((e) => { (adj[e.from] = adj[e.from] || []).push(e.to); (adj[e.to] = adj[e.to] || []).push(e.from); });
  for (let pass = 0; pass < 3; pass++) nodes.forEach((n) => {
    if (layer[n.id]) return;
    const c = {}; (adj[n.id] || []).forEach((m) => { if (layer[m]) c[layer[m]] = (c[layer[m]] || 0) + 1; });
    const best = Object.entries(c).sort((x, y) => y[1] - x[1])[0];
    if (best) layer[n.id] = best[0];
  });
  nodes.forEach((n) => { if (!layer[n.id]) layer[n.id] = ((p.fallback || []).find(([, re]) => re.test(n.type)) || ["compute"])[0]; });
  return layer;
}

const subGrid = (n) => { const cols = Math.max(1, Math.ceil(n / PER_COL)), rows = Math.min(n, PER_COL); return { cols, rows }; };

/** Nested nodes (Region > VPC > layer > inbound|core|outbound > resource) plus the dependency edges. Positions are computed once per graph. */
export function buildFlow(graph, selected, availability, p) {
  const rf = [];
  const titles = { ...DEFAULT_TITLES, ...(p.titles || {}) };
  const nodes = graph.nodes.filter((n) => !(p.hide && p.hide.test(n.type)));
  const shown = new Set(nodes.map((n) => n.id));
  const edgesIn = graph.edges.filter((e) => shown.has(e.from) && shown.has(e.to));
  const layerOf = assignLayers(nodes, edgesIn, p);
  const wr = graph.wrappers || {};
  const users = { id: "external.users", type: "external", label: p.usersLabel || "Users, browsers & external apps" };

  const defs = ["external", "edge", "compute", "data"].map((key) => {
    const members = key === "external" ? [users] : nodes.filter((n) => layerOf[n.id] === key);
    const subs = ROLES.map(([role, title]) => {
      const m = key === "external" ? (role === "core" ? [users] : []) : members.filter((n) => roleOf(p, n.type) === role);
      const g = subGrid(m.length);
      return { role, title, members: m, cols: m.length ? g.cols : 0, w: m.length ? g.cols * (NW + GAP) - GAP + 16 : EMPTY_W, h: m.length ? g.rows * (NH + GAP) - GAP + SUBHEAD + 12 : SUBHEAD + 40 };
    });
    const w = subs.reduce((t, x) => t + x.w, 0) + 8 * (subs.length + 1);
    return { key, subs, w, h: HEAD + Math.max(...subs.map((x) => x.h)) + 12 };
  });
  const H = Math.max(...defs.map((d) => d.h));
  const layerGap = 56, cloud = defs.filter((d) => d.key !== "external");
  const vpcW = cloud.reduce((t, d) => t + d.w, 0) + layerGap * (cloud.length - 1) + PAD * 2, vpcH = HEAD + H + PAD;
  const regionW = vpcW + PAD * 2, regionH = vpcH + HEAD + PAD;
  const ext = defs[0], extX = 0, extY = (regionH - H) / 2, regionX = ext.w + 70;

  const addLayer = (d, parentId, x, y) => {
    rf.push({ id: `layer.${d.key}`, type: "group", ...(parentId ? { parentId } : {}), position: { x, y }, data: { kind: "layer", label: titles[d.key] }, style: { width: d.w, height: H }, selectable: false, zIndex: 0 });
    let sx = 8;
    d.subs.forEach((sub) => {
      rf.push({ id: `sub.${d.key}.${sub.role}`, type: "group", parentId: `layer.${d.key}`, position: { x: sx, y: HEAD }, data: { kind: "sub", label: sub.title, empty: !sub.members.length }, style: { width: sub.w, height: H - HEAD - 12 }, selectable: false, zIndex: 1 });
      sub.members.forEach((n, i) => {
        const pos = { x: 8 + Math.floor(i / PER_COL) * (NW + GAP), y: SUBHEAD + 6 + (i % PER_COL) * (NH + GAP) };
        rf.push(n === users
          ? { id: users.id, type: "external", parentId: `sub.${d.key}.${sub.role}`, extent: "parent", position: pos, data: { label: users.label, type: "clients" }, selectable: false, zIndex: 2 }
          : { id: n.id, type: "resource", parentId: `sub.${d.key}.${sub.role}`, extent: "parent", position: pos, zIndex: 2, data: { ...n, cloud: p.cloud, icon: p.iconOf ? p.iconOf(n) : null, Icon: p.Icon ? p.Icon(n) : null, typeLabel: p.typeLabel ? p.typeLabel(n) : n.type, reason: availability[n.type]?.reason, selected: selected === n.id } });
      });
      sx += sub.w + 8;
    });
  };
  addLayer(ext, null, extX, extY);
  rf.push({ id: "box.region", type: "group", position: { x: regionX, y: 0 }, data: { kind: "region", label: wr.region || "" }, style: { width: regionW, height: regionH }, selectable: false, zIndex: 0 });
  rf.push({ id: "box.vpc", type: "group", parentId: "box.region", position: { x: PAD, y: HEAD }, data: { kind: "vpc", label: wr.network?.label || "", cidr: wr.network?.cidr, icon: p.networkIcon, cloud: p.cloud }, style: { width: vpcW, height: vpcH }, selectable: false, zIndex: 0 });
  let x = PAD; cloud.forEach((d) => { addLayer(d, "box.vpc", x, HEAD); x += d.w + layerGap; });

  // edges: real dependencies + users entering through the gateway layer
  const hi = (a, b) => selected && (a === selected || b === selected);
  const mk = (id, a, b, dashed) => ({ id, source: a, target: b, type: "smoothstep", zIndex: 3,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: hi(a, b) ? "#0972d3" : "#8a94a3" },
    style: { stroke: hi(a, b) ? "#0972d3" : "#8a94a3", strokeWidth: hi(a, b) ? 2.2 : 1.2, opacity: !selected || hi(a, b) ? 1 : 0.25, strokeDasharray: dashed ? "6 4" : undefined } });
  const edges = edgesIn.map((e, i) => mk(`e${i}`, e.from, e.to));
  nodes.filter((n) => p.entry.test(n.type)).forEach((n, i) => edges.push(mk(`u${i}`, users.id, n.id, true)));
  return { nodes: rf, edges };
}

function Inner({ graph, selected, onSelect, profile }) {
  const { fitView } = useReactFlow();
  const availability = graph.availability || {};
  // Positions live in state so dragging a tile or a box sticks; selection only restyles, it never re-lays-out.
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  useEffect(() => {
    setNodes(buildFlow(graph, null, availability, profile).nodes);
    const t = setTimeout(() => fitView({ padding: 0.12, duration: 250 }), 60);
    return () => clearTimeout(t);
  }, [graph]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setNodes((ns) => ns.map((n) => (n.type === "resource" ? { ...n, data: { ...n.data, selected: n.id === selected } } : n))); }, [selected, setNodes]);
  const edges = useMemo(() => buildFlow(graph, selected, availability, profile).edges, [graph, selected]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} nodeTypes={nodeTypes} minZoom={0.2} maxZoom={1.8}
      nodesDraggable nodesConnectable={false} elementsSelectable panOnDrag zoomOnScroll zoomOnPinch zoomOnDoubleClick={false}
      onNodeClick={(_, n) => n.type === "resource" && onSelect && onSelect(n.id)} onPaneClick={() => onSelect && onSelect(null)} proOptions={{ hideAttribution: true }}
      style={{ cursor: "grab" }}>
      <Background gap={20} color="#d5d9d9" />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeColor={(n) => (n.type === "group" ? "#d9c8ff" : RING[n.data?.status] || "#8a94a3")} style={{ height: 90, width: 140 }} />
    </ReactFlow>
  );
}

export default function InfraDiagram(props) {
  return <div style={{ height: props.height || 640, border: "1px solid #d5d9d9", borderRadius: 8, background: "#fafafa" }} data-testid="tf-diagram"><ReactFlowProvider><Inner {...props} /></ReactFlowProvider></div>;
}
