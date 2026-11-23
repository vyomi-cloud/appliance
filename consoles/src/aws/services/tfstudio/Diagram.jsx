/* Stack diagram on React Flow (xyflow, MIT): the usual layered architecture view, left to right - users/external apps, gateways / firewalls /
 * load balancers, services & serverless, data - all inside a Region > VPC wrapper, with identity / secrets / monitoring in a shared band.
 * Icon tiles with labels, arrowed dependency edges, drag / zoom / pan, minimap. Icons are Vyomi's own service tiles (common/icons); a different icon
 * set plugs in through ICON_FOR / the `icons` prop. Availability is the tile's ring: solid green = in Vyomi, dashed amber = planned,
 * dotted red = not possible in Vyomi. */
import { useEffect, useMemo } from "react";
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ServiceIcon from "../../../common/icons/ServiceIcon.jsx";

const NW = 132, NH = 96, PAD = 28, HEAD = 34;
const RING = { supported: "#1d8102", planned: "#b7791f", not_possible: "#d13212" };
const DASH = { supported: "solid", planned: "dashed", not_possible: "dotted" };
/** Terraform service -> icon id in common/icons/aws.js (anything else falls back to the generic tile in its category). */
const ICON_FOR = { vpc: "vpc", s3: "s3", iam: "iam", lambda: "lambda", apigateway: "apigateway", rds: "rds", secretsmanager: "secretsmanager", cloudwatch: "cloudwatch", kms: "kms", sqs: "sqs", sns: "sns", dynamodb: "dynamodb", ec2: "ec2" };
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

function ResourceNode({ data }) {
  return (
    <div title={`${data.type}${data.reason ? " - " + data.reason : ""}`} style={{ width: NW, textAlign: "center", opacity: data.dim ? 0.35 : 1 }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ width: 52, height: 52, margin: "0 auto", borderRadius: 10, padding: 4, background: "#fff", boxSizing: "border-box",
        border: `2px ${DASH[data.status]} ${RING[data.status]}`, boxShadow: data.selected ? "0 0 0 3px #0972d340" : "none" }}>
        <ServiceIcon cloud="aws" id={ICON_FOR[data.service] || data.service} size={40} />
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#16191f", marginTop: 4, lineHeight: "14px" }}>{clip(data.label, 20)}</div>
      <div style={{ fontSize: 10.5, color: "#5f6b7a", lineHeight: "13px" }}>{clip(data.type.replace(/^aws_/, ""), 24)}</div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}
const GROUP_STYLE = {
  region: { border: "2px dashed #7a8699", bg: "#ffffff80", color: "#414d5c", icon: null },
  vpc: { border: "2px solid #8c4fff", bg: "#8c4fff0d", color: "#6b2fd9", icon: "vpc" },
  layer: { border: "1.5px dashed #9aa3b2", bg: "#ffffffb3", color: "#414d5c", icon: null },
};
function GroupNode({ data }) {
  const g = GROUP_STYLE[data.kind] || GROUP_STYLE.layer;
  return (
    <div style={{ width: "100%", height: "100%", border: g.border, borderRadius: 10, background: g.bg, boxSizing: "border-box", position: "relative" }}>
      <div style={{ position: "absolute", top: 7, left: 10, display: "flex", alignItems: "center", gap: 6, fontSize: data.kind === "layer" ? 11.5 : 12.5, fontWeight: 700, color: g.color }}>
        {g.icon && <ServiceIcon cloud="aws" id={g.icon} size={18} />}{data.label}{data.cidr ? <span style={{ fontWeight: 400, color: "#5f6b7a" }}>{data.cidr}</span> : null}
      </div>
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

/** Which layer a Terraform resource type belongs to. `skip` = drawn as the wrapper itself, not as a tile. */
const LAYER_RULES = [
  ["skip", /^aws_vpc$/],
  ["network", /^aws_(subnet|route_table|route\b|db_subnet_group|vpc_endpoint|network_interface|eip)/],
  ["edge", /^aws_(api_gateway|apigatewayv2|internet_gateway|nat_gateway|lb|alb|elb|security_group|network_acl|wafv2|cloudfront|route53)/],
  ["data", /^aws_(db_|rds_|dynamodb|s3_|elasticache|docdb|neptune|redshift|efs|ebs)/],
  ["shared", /^aws_(iam_|kms_|secretsmanager_|cloudwatch_log|cloudwatch_metric|cloudwatch_dashboard|ssm_|backup_)/],
  ["compute", /^aws_(lambda_|instance|launch_|autoscaling|ecs_|eks_|sfn_|sqs_|sns_|cloudwatch_event|kinesis|ecr_)/],
];
export const layerOf = (type) => (LAYER_RULES.find(([, re]) => re.test(type)) || ["shared"])[0];
const LAYERS = [
  { key: "external", title: "1 · Users & external apps" },
  { key: "edge", title: "2 · Gateway, firewall & load balancing" },
  { key: "compute", title: "3 · Services & serverless" },
  { key: "data", title: "4 · Data & storage" },
];
const BANDS = [{ key: "network", title: "Network: subnets & routing" }, { key: "shared", title: "Identity, secrets & monitoring" }];
const GAP = 12;

const gridFor = (n, maxCols) => { const cols = Math.max(1, Math.min(maxCols, n <= 4 ? 1 : n <= 10 ? 2 : 3)); return { cols, rows: Math.ceil(n / cols) || 1 }; };
const place = (members, cols, ox, oy) => Object.fromEntries(members.map((n, i) => [n.id, { x: ox + (i % cols) * (NW + GAP), y: oy + Math.floor(i / cols) * (NH + GAP) }]));

/** Builds the nested nodes (Region > VPC > layer > resource) and the dependency edges. Positions are computed once per graph. */
export function buildFlow(graph, selected, availability) {
  const rf = [];
  const nodes = graph.nodes.filter((n) => layerOf(n.type) !== "skip");
  const by = { edge: [], compute: [], data: [], network: [], shared: [] };
  nodes.forEach((n) => by[layerOf(n.type)].push(n));
  const vpc = (graph.groups || [])[0];
  const region = graph.region || "us-east-1";

  // size each layer box
  const layers = ["edge", "compute", "data"].map((k) => {
    const members = by[k], { cols, rows } = gridFor(members.length, 3);
    return { key: k, title: LAYERS.find((l) => l.key === k).title, members, cols, w: Math.max(cols, 1) * (NW + GAP) - GAP + PAD * 2, h: Math.max(rows, 1) * (NH + GAP) - GAP + HEAD + PAD };
  });
  const layersH = Math.max(...layers.map((l) => l.h));
  const innerW = layers.reduce((w, l) => w + l.w, 0) + GAP * 2 * (layers.length - 1) + GAP * 2;     // layers side by side with arrows' room
  const layerGap = 56;
  const rowW = layers.reduce((w, l) => w + l.w, 0) + layerGap * (layers.length - 1);
  const bandCols = Math.max(1, Math.floor((rowW - PAD * 2 + GAP) / (NW + GAP)));
  const bands = BANDS.map((b) => ({ ...b, members: by[b.key] })).filter((b) => b.members.length).map((b) => ({ ...b, h: Math.ceil(b.members.length / bandCols) * (NH + GAP) - GAP + HEAD + PAD }));
  const bandsH = bands.reduce((h, b) => h + 24 + b.h, 0);
  const vpcW = rowW + PAD * 2, vpcH = HEAD + layersH + bandsH + PAD;
  const regionW = vpcW + PAD * 2, regionH = vpcH + HEAD + PAD;
  const extW = NW + PAD * 2, extH = NH + HEAD + PAD;

  // parents first
  rf.push({ id: "box.external", type: "group", position: { x: 0, y: regionH / 2 - extH / 2 }, data: { kind: "layer", label: LAYERS[0].title }, style: { width: extW, height: extH }, selectable: false, zIndex: 0 });
  rf.push({ id: "external.users", type: "external", parentId: "box.external", extent: "parent", position: { x: PAD, y: HEAD }, data: { label: "Users, browsers & external apps", type: "clients" }, draggable: true, selectable: false, zIndex: 2 });
  const rx = extW + 70;
  rf.push({ id: "box.region", type: "group", position: { x: rx, y: 0 }, data: { kind: "region", label: `AWS Region · ${region}` }, style: { width: regionW, height: regionH }, selectable: false, zIndex: 0 });
  rf.push({ id: "box.vpc", type: "group", parentId: "box.region", position: { x: PAD, y: HEAD }, data: { kind: "vpc", label: vpc ? `VPC ${vpc.label}` : "VPC", cidr: vpc?.cidr }, style: { width: vpcW, height: vpcH }, selectable: false, zIndex: 0 });
  let x = PAD;
  layers.forEach((l) => {
    rf.push({ id: `box.${l.key}`, type: "group", parentId: "box.vpc", position: { x, y: HEAD }, data: { kind: "layer", label: l.title }, style: { width: l.w, height: l.h }, selectable: false, zIndex: 0 });
    const pos = place(l.members, l.cols, PAD, HEAD);
    l.members.forEach((n) => rf.push({ id: n.id, type: "resource", parentId: `box.${l.key}`, extent: "parent", position: pos[n.id], zIndex: 2, data: { ...n, reason: availability[n.type]?.reason, selected: selected === n.id } }));
    x += l.w + layerGap;
  });
  let by0 = HEAD + layersH;
  bands.forEach((b) => {
    by0 += 24;
    rf.push({ id: `box.${b.key}`, type: "group", parentId: "box.vpc", position: { x: PAD, y: by0 }, data: { kind: "layer", label: b.title }, style: { width: rowW, height: b.h }, selectable: false, zIndex: 0 });
    const pos = place(b.members, bandCols, PAD, HEAD);
    b.members.forEach((n) => rf.push({ id: n.id, type: "resource", parentId: `box.${b.key}`, extent: "parent", position: pos[n.id], zIndex: 2, data: { ...n, reason: availability[n.type]?.reason, selected: selected === n.id } }));
    by0 += b.h;
  });

  // edges: real dependencies (drawn from the dependent to what it needs) + users entering through the edge layer
  const shown = new Set(nodes.map((n) => n.id));
  const hi = (a, b) => selected && (a === selected || b === selected);
  const mk = (id, a, b, dashed) => ({ id, source: a, target: b, type: "smoothstep", zIndex: 1,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: hi(a, b) ? "#0972d3" : "#8a94a3" },
    style: { stroke: hi(a, b) ? "#0972d3" : "#8a94a3", strokeWidth: hi(a, b) ? 2.2 : 1.2, opacity: !selected || hi(a, b) ? 1 : 0.25, strokeDasharray: dashed ? "6 4" : undefined } });
  const edges = graph.edges.filter((e) => shown.has(e.from) && shown.has(e.to)).map((e, i) => mk(`e${i}`, e.from, e.to));
  const entry = nodes.filter((n) => /^aws_(api_gateway_rest_api|apigatewayv2_api|internet_gateway|lb|alb|elb|cloudfront_distribution)$/.test(n.type));
  entry.forEach((n, i) => edges.push(mk(`u${i}`, "external.users", n.id, true)));
  return { nodes: rf, edges };
}

function Inner({ graph, selected, onSelect }) {
  const { fitView } = useReactFlow();
  const availability = graph.availability || {};
  // Positions live in state so dragging a tile or a box sticks; selection only restyles, it never re-lays-out.
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  useEffect(() => {
    setNodes(buildFlow(graph, null, availability).nodes);
    const t = setTimeout(() => fitView({ padding: 0.12, duration: 250 }), 60);
    return () => clearTimeout(t);
  }, [graph]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setNodes((ns) => ns.map((n) => (n.type === "resource" ? { ...n, data: { ...n.data, selected: n.id === selected } } : n))); }, [selected, setNodes]);
  const edges = useMemo(() => buildFlow(graph, selected, availability).edges, [graph, selected]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} nodeTypes={nodeTypes} minZoom={0.2} maxZoom={1.8}
      nodesDraggable nodesConnectable={false} elementsSelectable panOnDrag zoomOnScroll zoomOnPinch zoomOnDoubleClick={false}
      onNodeClick={(_, n) => n.type === "resource" && onSelect(n.id)} onPaneClick={() => onSelect(null)} proOptions={{ hideAttribution: true }}
      style={{ cursor: "grab" }}>
      <Background gap={20} color="#d5d9d9" />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeColor={(n) => (n.type === "group" ? "#d9c8ff" : RING[n.data?.status] || "#8a94a3")} style={{ height: 90, width: 140 }} />
    </ReactFlow>
  );
}

export default function Diagram(props) {
  return <div style={{ height: 640, border: "1px solid #d5d9d9", borderRadius: 8, background: "#fafafa" }} data-testid="tf-diagram"><ReactFlowProvider><Inner {...props} /></ReactFlowProvider></div>;
}
