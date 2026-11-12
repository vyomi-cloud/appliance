/* EventBridge rule Builder (AWS-10): the visual Palette / Canvas / Triggering event editor. It is a view over the same
 * state the Create-rule form submits (event pattern + targets), so what you draw is exactly what PutRule/PutTargets
 * send — drawing an event node and wiring it to target nodes IS the rule. */
import { useEffect, useMemo, useRef, useState } from "react";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Textarea from "@cloudscape-design/components/textarea";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Canvas from "../../kit/Canvas.jsx";

export const EB_PALETTE = [
  { type: "event", label: "Triggering event", group: "Event", color: "#0972d3", hint: "The event pattern the rule matches", defaults: { source: "", detailType: "", extra: "" } },
  { type: "target", label: "Builder target node", group: "Targets", color: "#037f0c", hint: "SQS, SNS, Lambda, Step Functions or Kinesis", defaults: { arn: "", label: "", input: "" } },
];

const csv = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);

export function patternOf(ev) {
  let extra = {}; try { extra = ev?.data?.extra ? JSON.parse(ev.data.extra) : {}; } catch { extra = {}; }
  const p = {};
  if (csv(ev?.data?.source).length) p.source = csv(ev.data.source);
  if (csv(ev?.data?.detailType).length) p["detail-type"] = csv(ev.data.detailType);
  return JSON.stringify({ ...p, ...extra });
}
const sig = (patternStr, targets) => JSON.stringify([patternStr, targets.map((t) => [t.arn, t.input || "", t.partitionKeyPath || ""])]);

function fromProps(pattern, targets) {
  let p = {}; try { p = pattern.trim() ? JSON.parse(pattern) : {}; } catch { p = {}; }
  const { source, "detail-type": dt, ...rest } = p;
  const nodes = [{ id: "ev", type: "event", label: "Triggering event", x: 24, y: 120, data: {
    source: [].concat(source || []).join(", "), detailType: [].concat(dt || []).join(", "), extra: Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "" } }];
  const edges = [];
  targets.forEach((t, i) => {
    const id = `t${i}`;
    nodes.push({ id, type: "target", label: (t.label || t.arn || "Target").split(":").pop(), x: 320, y: 24 + i * 84, data: { arn: t.arn, label: t.label, input: t.input || "", tid: t.id, partitionKeyPath: t.partitionKeyPath || "" } });
    edges.push({ id: `e${i}`, from: "ev", to: id });
  });
  return { nodes, edges };
}

export default function RuleBuilder({ pattern, setPattern, targets, setTargets, options }) {
  const [graph, setGraph] = useState(() => fromProps(pattern, targets));
  const [selected, setSelected] = useState(null);
  const last = useRef(null);
  const incoming = useMemo(() => {
    let norm = pattern; try { norm = JSON.stringify(pattern.trim() ? JSON.parse(pattern) : {}); } catch { /* keep */ }
    return sig(norm, targets);
  }, [pattern, targets]);

  useEffect(() => {
    try { if (pattern.trim()) JSON.parse(pattern); } catch { return; }
    if (last.current !== null && incoming === last.current) return;
    if (last.current === null) { last.current = incoming; return; }  // first render: graph already built from props
    last.current = incoming;
    setGraph((g) => { const f = fromProps(pattern, targets); const ev = g.nodes.find((n) => n.type === "event"); if (ev) { f.nodes[0].x = ev.x; f.nodes[0].y = ev.y; } return f; });
  }, [incoming]); // eslint-disable-line react-hooks/exhaustive-deps

  const emit = (g) => {
    setGraph(g);
    const ev = g.nodes.find((n) => n.type === "event");
    const wired = g.nodes.filter((n) => n.type === "target" && n.data?.arn && g.edges.some((e) => e.from === ev?.id && e.to === n.id));
    const newTargets = wired.map((n, i) => ({ id: n.data.tid || `t${i + 1}`, arn: n.data.arn, label: n.data.label || n.data.arn, input: n.data.input || "", partitionKeyPath: n.data.partitionKeyPath || "" }));
    const pat = ev ? patternOf(ev) : "{}";
    last.current = sig(pat, newTargets);
    setPattern(JSON.stringify(JSON.parse(pat), null, 2));
    setTargets(newTargets);
  };

  return (
    <Canvas ariaLabel="Rule builder canvas" palette={EB_PALETTE} nodes={graph.nodes} edges={graph.edges} onChange={emit}
      selectedId={selected} onSelect={setSelected} height={Math.max(300, 80 + graph.nodes.length * 44)}
      emptyHint="Add a Triggering event, then add Targets and connect them."
      canConnect={(a, b) => (a.type !== "event" || b.type !== "target" ? "Connect the Triggering event to a Target." : true)}
      renderInspector={(n, patch) => n.type === "event" ? (
        <SpaceBetween size="s">
          <FormField label="Source" description="Comma-separated, e.g. my.app"><Input value={n.data.source || ""} ariaLabel="Event source" onChange={({ detail }) => patch({ data: { source: detail.value } })} /></FormField>
          <FormField label="Detail type" description="Comma-separated"><Input value={n.data.detailType || ""} ariaLabel="Event detail type" onChange={({ detail }) => patch({ data: { detailType: detail.value } })} /></FormField>
          <FormField label="Other pattern fields (JSON)" description='e.g. {"detail":{"state":["ok"]}}'><Textarea rows={5} value={n.data.extra || ""} ariaLabel="Other pattern fields" onChange={({ detail }) => patch({ data: { extra: detail.value } })} /></FormField>
        </SpaceBetween>
      ) : (
        <SpaceBetween size="s">
          <FormField label="Target"><Select selectedOption={n.data.arn ? { value: n.data.arn, label: n.data.label } : null} placeholder="Select a target" ariaLabel="Builder target"
            options={options.map((o) => ({ value: o.arn, label: o.label }))}
            onChange={({ detail }) => patch({ label: detail.selectedOption.label.split(":").pop(), data: { arn: detail.selectedOption.value, label: detail.selectedOption.label } })} /></FormField>
          <FormField label="Input - optional"><Textarea rows={3} value={n.data.input || ""} ariaLabel="Builder target input" onChange={({ detail }) => patch({ data: { input: detail.value } })} /></FormField>
        </SpaceBetween>
      )} />
  );
}
