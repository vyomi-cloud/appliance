/* Shared visual canvas kit (AWS-10) — one reusable drag-and-drop node/edge editor used by
 * CloudFormation Template Studio, the EventBridge rule Builder and the Lambda Infrastructure
 * Composer. The canvas itself holds no truth: each host owns a typed model (nodes + edges),
 * serialises it to the real service payload (CloudFormation template, event pattern + targets,
 * a stack + functions) and sends it through the real service APIs. Nothing here is a picture.
 *
 *   <Canvas palette nodes edges onChange canConnect selectedId onSelect renderInspector />
 *   palette:   [{ type, label, group?, color?, hint?, defaults?, idPrefix? }]   (idPrefix => id and label become Prefix1, Prefix2, ...)
 *   nodes:     [{ id, type, label, x, y, data? }]
 *   edges:     [{ id, from, to }]
 *   onChange:  ({ nodes, edges }) => void   (every move / add / delete / connect)
 *   canConnect:(fromNode, toNode) => boolean | string   (string = reason it is refused)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";

export const NODE_W = 168;
export const NODE_H = 52;

let _seq = 0;
export const newId = (p = "n") => `${p}${Date.now().toString(36)}${(_seq++).toString(36)}`;

const GROUP_COLORS = ["#0972d3", "#037f0c", "#b7791f", "#8456ce", "#d91515", "#0f766e", "#6b7280"];
const colorOf = (palette, type, i) => palette.find((p) => p.type === type)?.color || GROUP_COLORS[(i ?? 0) % GROUP_COLORS.length];

function edgePath(a, b) {
  const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
  const dx = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}

export default function Canvas({
  palette, nodes, edges, onChange, canConnect, selectedId, onSelect, renderInspector,
  height = 420, emptyHint = "Drag an item from the palette onto the canvas, or choose Add.", ariaLabel = "Canvas",
}) {
  const svgRef = useRef(null);
  const [drag, setDrag] = useState(null);       // { id, dx, dy } moving a node
  const [link, setLink] = useState(null);       // { from, x, y } rubber band
  const [selEdge, setSelEdge] = useState(null);
  const [notice, setNotice] = useState(null);
  const nodesRef = useRef(nodes); nodesRef.current = nodes;
  const edgesRef = useRef(edges); edgesRef.current = edges;

  const pt = (e) => {
    const r = svgRef.current.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const emit = useCallback((n, e) => onChange({ nodes: n, edges: e }), [onChange]);

  const addNode = (type, at) => {
    const def = palette.find((p) => p.type === type);
    if (!def) return;
    const count = nodesRef.current.length;
    const pos = at || { x: 24 + (count % 3) * (NODE_W + 40), y: 24 + Math.floor(count / 3) * (NODE_H + 36) };
    let id = newId(), label = def.label;
    if (def.idPrefix) { let k = 1; while (nodesRef.current.some((n) => n.id === `${def.idPrefix}${k}`)) k++; id = label = `${def.idPrefix}${k}`; }
    const node = { id, type, label, x: Math.max(4, pos.x), y: Math.max(4, pos.y), data: def.defaults ? JSON.parse(JSON.stringify(def.defaults)) : {} };
    emit([...nodesRef.current, node], edgesRef.current);
    onSelect?.(node.id);
  };
  const removeNode = (id) => {
    emit(nodesRef.current.filter((n) => n.id !== id), edgesRef.current.filter((e) => e.from !== id && e.to !== id));
    onSelect?.(null);
  };
  const removeEdge = (id) => { emit(nodesRef.current, edgesRef.current.filter((e) => e.id !== id)); setSelEdge(null); };

  const tryConnect = (fromId, toId) => {
    if (fromId === toId) return;
    const a = nodesRef.current.find((n) => n.id === fromId), b = nodesRef.current.find((n) => n.id === toId);
    if (!a || !b) return;
    if (edgesRef.current.some((e) => e.from === fromId && e.to === toId)) { setNotice("Those two are already connected."); return; }
    const ok = canConnect ? canConnect(a, b) : true;
    if (ok !== true && ok !== undefined) { setNotice(typeof ok === "string" ? ok : "That connection isn't allowed."); return; }
    setNotice(null);
    emit(nodesRef.current, [...edgesRef.current, { id: newId("e"), from: fromId, to: toId }]);
  };

  // Pointer interaction for moving nodes + rubber-band connections.
  useEffect(() => {
    if (!drag && !link) return undefined;
    const move = (e) => {
      const p = pt(e);
      if (drag) {
        emit(nodesRef.current.map((n) => (n.id === drag.id ? { ...n, x: Math.max(0, p.x - drag.dx), y: Math.max(0, p.y - drag.dy) } : n)), edgesRef.current);
      } else if (link) setLink({ ...link, x: p.x, y: p.y });
    };
    const up = (e) => {
      if (link) {
        const p = pt(e);
        const hit = nodesRef.current.find((n) => p.x >= n.x && p.x <= n.x + NODE_W && p.y >= n.y && p.y <= n.y + NODE_H);
        if (hit) tryConnect(link.from, hit.id);
      }
      setDrag(null); setLink(null);
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [drag, link]); // eslint-disable-line react-hooks/exhaustive-deps

  const onKey = (e) => {
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (selEdge) removeEdge(selEdge); else if (selectedId) removeNode(selectedId);
  };

  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const selected = nodes.find((n) => n.id === selectedId);
  const groups = [...new Set(palette.map((p) => p.group || ""))];

  return (
    <div data-vyomi-canvas="" style={{ display: "flex", gap: 12, alignItems: "stretch" }}>
      <div style={{ width: 190, flex: "none", borderRight: "1px solid #d5dbdb", paddingRight: 12 }} data-vyomi-canvas-palette="">
        <Box variant="h4" padding={{ bottom: "xs" }}>Palette</Box>
        <SpaceBetween size="xs">
          {groups.map((g) => (
            <div key={g}>
              {g && <Box variant="small" color="text-body-secondary" padding={{ bottom: "xxs" }}>{g}</Box>}
              {palette.filter((p) => (p.group || "") === g).map((p, i) => (
                <div key={p.type} draggable data-palette-type={p.type}
                  onDragStart={(e) => { e.dataTransfer.setData("text/vyomi-canvas", p.type); e.dataTransfer.effectAllowed = "copy"; }}
                  style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 6px", margin: "2px 0", border: "1px solid #d5dbdb", borderRadius: 6, cursor: "grab", background: "#fff", fontSize: 13 }}
                  title={p.hint || p.label}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: colorOf(palette, p.type, i), flex: "none" }} />
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.label}</span>
                  <Button variant="inline-icon" iconName="add-plus" ariaLabel={`Add ${p.label}`} onClick={() => addNode(p.type)} />
                </div>
              ))}
            </div>
          ))}
        </SpaceBetween>
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div tabIndex={0} onKeyDown={onKey} style={{ outline: "none" }}
          onDragOver={(e) => { if (e.dataTransfer.types.includes("text/vyomi-canvas")) e.preventDefault(); }}
          onDrop={(e) => { const t = e.dataTransfer.getData("text/vyomi-canvas"); if (t) { e.preventDefault(); const p = pt(e); addNode(t, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 }); } }}>
          <svg ref={svgRef} width="100%" height={height} role="application" aria-label={ariaLabel} data-vyomi-canvas-surface=""
            style={{ background: "#f9fafb", backgroundImage: "radial-gradient(#d5dbdb 1px, transparent 1px)", backgroundSize: "16px 16px", border: "1px solid #d5dbdb", borderRadius: 8, touchAction: "none" }}
            onPointerDown={(e) => { if (e.target === svgRef.current) { onSelect?.(null); setSelEdge(null); } }}>
            <defs><marker id="vy-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#5f6b7a" /></marker></defs>
            {edges.map((e) => {
              const a = byId[e.from], b = byId[e.to];
              if (!a || !b) return null;
              const d = edgePath(a, b);
              return (
                <g key={e.id} data-edge={`${e.from}>${e.to}`} onPointerDown={(ev) => { ev.stopPropagation(); setSelEdge(e.id); onSelect?.(null); }} style={{ cursor: "pointer" }}>
                  <path d={d} stroke="transparent" strokeWidth="12" fill="none" />
                  <path d={d} stroke={selEdge === e.id ? "#d91515" : "#5f6b7a"} strokeWidth={selEdge === e.id ? 3 : 2} fill="none" markerEnd="url(#vy-arrow)" />
                </g>
              );
            })}
            {link && byId[link.from] && <path d={`M${byId[link.from].x + NODE_W},${byId[link.from].y + NODE_H / 2} L${link.x},${link.y}`} stroke="#0972d3" strokeDasharray="5 4" strokeWidth="2" fill="none" />}
            {nodes.map((n, i) => {
              const c = colorOf(palette, n.type, i);
              return (
                <g key={n.id} data-node={n.id} data-node-type={n.type} transform={`translate(${n.x},${n.y})`} style={{ cursor: "move" }}
                  onPointerDown={(e) => { e.stopPropagation(); setSelEdge(null); onSelect?.(n.id); const p = pt(e); setDrag({ id: n.id, dx: p.x - n.x, dy: p.y - n.y }); }}>
                  <rect width={NODE_W} height={NODE_H} rx="8" fill="#fff" stroke={n.id === selectedId ? "#0972d3" : "#aab7b8"} strokeWidth={n.id === selectedId ? 3 : 1.5} />
                  <rect width="6" height={NODE_H} rx="3" fill={c} />
                  <text x="16" y="21" fontSize="13" fontWeight="700" fill="#16191f">{String(n.label).slice(0, 22)}</text>
                  <text x="16" y="38" fontSize="11" fill="#5f6b7a">{(palette.find((p) => p.type === n.type)?.label || n.type).slice(0, 26)}</text>
                  <circle cx={NODE_W} cy={NODE_H / 2} r="7" fill="#fff" stroke="#0972d3" strokeWidth="2" data-handle-out={n.id} style={{ cursor: "crosshair" }}
                    onPointerDown={(e) => { e.stopPropagation(); onSelect?.(n.id); const p = pt(e); setLink({ from: n.id, x: p.x, y: p.y }); }} />
                  <circle cx="0" cy={NODE_H / 2} r="4" fill="#0972d3" />
                </g>
              );
            })}
            {!nodes.length && <text x="50%" y="50%" textAnchor="middle" fontSize="13" fill="#5f6b7a">{emptyHint}</text>}
          </svg>
        </div>
        <Box variant="small" color={notice ? "text-status-error" : "text-body-secondary"} padding={{ top: "xs" }} data-canvas-notice="">
          {notice || "Drag nodes to arrange. Drag from a node's right handle onto another node to connect. Click a node or connector, then press Delete to remove it."}
        </Box>
      </div>

      {renderInspector && (
        <div style={{ width: 280, flex: "none", borderLeft: "1px solid #d5dbdb", paddingLeft: 12 }} data-vyomi-canvas-inspector="">
          <Box variant="h4" padding={{ bottom: "xs" }}>Properties</Box>
          {selected
            ? <SpaceBetween size="s">
                {renderInspector(selected, (patch) => emit(nodesRef.current.map((n) => (n.id === selected.id ? { ...n, ...patch, data: { ...n.data, ...(patch.data || {}) } } : n)), edgesRef.current))}
                <Button iconName="remove" onClick={() => removeNode(selected.id)}>Delete node</Button>
              </SpaceBetween>
            : <Box color="text-body-secondary" variant="small">Select a node to edit its properties.</Box>}
        </div>
      )}
    </div>
  );
}
