/* Stack diagram on React Flow (xyflow, MIT) with dagre auto-layout: the usual architecture-diagram look (nested VPC box, icon tiles
 * with labels, arrowed dependency edges, zoom/pan, minimap). Icons are Vyomi's own service tiles (common/icons); a different icon
 * set plugs in through ICON_FOR / the `icons` prop. Availability is the tile's ring: solid green = in Vyomi, dashed amber = planned,
 * dotted red = not possible in Vyomi. */
import { useEffect, useMemo } from "react";
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
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
function GroupNode({ data }) {
  const vpc = data.kind === "vpc";
  return (
    <div style={{ width: "100%", height: "100%", border: `2px ${vpc ? "solid" : "dashed"} ${vpc ? "#8c4fff" : "#9aa3b2"}`, borderRadius: 10, background: vpc ? "#8c4fff0d" : "#ffffffb3", boxSizing: "border-box", position: "relative" }}>
      <div style={{ position: "absolute", top: 7, left: 10, display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 700, color: vpc ? "#6b2fd9" : "#414d5c" }}>
        <ServiceIcon cloud="aws" id={vpc ? "vpc" : ICON_FOR[data.service] || data.service} size={18} />{data.label}{data.cidr ? <span style={{ fontWeight: 400, color: "#5f6b7a" }}>{data.cidr}</span> : null}
      </div>
    </div>
  );
}
const nodeTypes = { resource: ResourceNode, group: GroupNode };

function layered(nodes, edges, rankdir = "LR") {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir, nodesep: 28, ranksep: 70, marginx: 10, marginy: 10 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: n.w, height: n.h }));
  edges.forEach((e) => { if (g.hasNode(e.from) && g.hasNode(e.to)) g.setEdge(e.from, e.to); });
  dagre.layout(g);
  const out = {}; nodes.forEach((n) => { const p = g.node(n.id); out[n.id] = { x: p.x - n.w / 2, y: p.y - n.h / 2 }; });
  const gi = g.graph();
  return { pos: out, w: gi.width || 0, h: gi.height || 0 };
}

const SERVICE_TITLE = { vpc: "VPC", s3: "S3", iam: "IAM", lambda: "Lambda", apigateway: "API Gateway", rds: "RDS", secretsmanager: "Secrets Manager", cloudwatch: "CloudWatch", kms: "KMS", sqs: "SQS", sns: "SNS", dynamodb: "DynamoDB", ec2: "EC2" };

/** Boxes: one per VPC (members laid out top-to-bottom by dependency) and one per service for everything outside a VPC (a compact grid).
 *  The boxes are then ranked left-to-right by dagre, so the diagram reads as service groups connected by dependency arrows. */
export function buildFlow(graph, selected, availability) {
  const rf = [];
  const boxes = [];
  const inGroup = new Map(graph.nodes.filter((n) => n.group).map((n) => [n.id, n.group]));
  graph.groups.forEach((grp) => {
    const members = graph.nodes.filter((n) => n.group === grp.id);
    const l = layered(members.map((n) => ({ id: n.id, w: NW, h: NH })), graph.edges.filter((e) => inGroup.get(e.from) === grp.id && inGroup.get(e.to) === grp.id), "TB");
    boxes.push({ id: grp.id, kind: "vpc", title: `VPC ${grp.label}`, cidr: grp.cidr, members, pos: Object.fromEntries(members.map((n) => [n.id, { x: PAD + l.pos[n.id].x, y: HEAD + l.pos[n.id].y }])), w: l.w + PAD * 2, h: l.h + PAD + HEAD });
  });
  const rest = graph.nodes.filter((n) => !n.group);
  [...new Set(rest.map((n) => n.service))].sort().forEach((svc) => {
    const members = rest.filter((n) => n.service === svc);
    const cols = Math.min(members.length, members.length > 6 ? 3 : 2), rows = Math.ceil(members.length / cols);
    boxes.push({ id: `svc.${svc}`, kind: "service", service: svc, title: SERVICE_TITLE[svc] || svc, members,
      pos: Object.fromEntries(members.map((n, i) => [n.id, { x: PAD + (i % cols) * (NW + 8), y: HEAD + Math.floor(i / cols) * (NH + 6) }])),
      w: cols * (NW + 8) - 8 + PAD * 2, h: rows * (NH + 6) - 6 + HEAD + PAD });
  });
  const boxOf = new Map(); boxes.forEach((b) => b.members.forEach((n) => boxOf.set(n.id, b.id)));
  const top = layered(boxes.map((b) => ({ id: b.id, w: b.w, h: b.h })),
    graph.edges.map((e) => ({ from: boxOf.get(e.from), to: boxOf.get(e.to) })).filter((e) => e.from && e.to && e.from !== e.to), "TB");
  boxes.forEach((b) => {
    rf.push({ id: b.id, type: "group", position: top.pos[b.id], data: { kind: b.kind, label: b.title, cidr: b.cidr, service: b.service }, style: { width: b.w, height: b.h }, selectable: false, zIndex: 0 });
    b.members.forEach((n) => rf.push({ id: n.id, type: "resource", parentId: b.id, extent: "parent", position: b.pos[n.id], zIndex: 2,
      data: { ...n, reason: availability[n.type]?.reason, selected: selected === n.id } }));
  });
  const hi = (e) => selected && (e.from === selected || e.to === selected);
  const edges = graph.edges.map((e, i) => ({ id: `e${i}`, source: e.from, target: e.to, type: "smoothstep", zIndex: 1,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: hi(e) ? "#0972d3" : "#8a94a3" },
    style: { stroke: hi(e) ? "#0972d3" : "#8a94a3", strokeWidth: hi(e) ? 2.2 : 1.2, opacity: !selected || hi(e) ? 1 : 0.25 } }));
  return { nodes: rf, edges };
}

function Inner({ graph, selected, onSelect }) {
  const { fitView } = useReactFlow();
  const flow = useMemo(() => buildFlow(graph, selected, graph.availability || {}), [graph, selected]);
  useEffect(() => { const t = setTimeout(() => fitView({ padding: 0.12, duration: 250 }), 50); return () => clearTimeout(t); }, [graph, fitView]);
  return (
    <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} fitView minZoom={0.2} maxZoom={1.8} nodesConnectable={false}
      onNodeClick={(_, n) => n.type === "resource" && onSelect(n.id)} onPaneClick={() => onSelect(null)} proOptions={{ hideAttribution: true }}>
      <Background gap={20} color="#d5d9d9" />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeColor={(n) => (n.type === "group" ? "#d9c8ff" : RING[n.data?.status] || "#8a94a3")} style={{ height: 90, width: 140 }} />
    </ReactFlow>
  );
}

export default function Diagram(props) {
  return <div style={{ height: 640, border: "1px solid #d5d9d9", borderRadius: 8, background: "#fafafa" }} data-testid="tf-diagram"><ReactFlowProvider><Inner {...props} /></ReactFlowProvider></div>;
}
