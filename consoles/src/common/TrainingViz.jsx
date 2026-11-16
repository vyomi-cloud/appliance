/* Shared, framework-neutral training widgets (plain SVG/DOM, theme via inheritance): used by the AWS (Cloudscape), GCP (MUI) and
 * Azure (Fluent) consoles so the chart/progress logic exists once. Each console wraps them in its own containers. */
import { pct, num } from "./training.js";

const C = { loss: "#c2410c", acc: "#1d4ed8", base: "#6b7280", grid: "rgba(128,128,128,.35)" };   // orange vs blue, also told apart by dash + label

/** Per-epoch loss (dashed, left axis) and accuracy (solid, right axis, 0-1). */
export function TrainingChart({ metrics = [], epochs = 0, width = 560, height = 220 }) {
  const m = metrics.filter((x) => x && x.epoch != null);
  const pad = { l: 44, r: 44, t: 12, b: 30 }, W = width - pad.l - pad.r, H = height - pad.t - pad.b;
  const n = Math.max(epochs || 0, m.length, 2);
  const maxLoss = Math.max(0.1, ...m.map((x) => Number(x.loss) || 0)) * 1.1;
  const x = (e) => pad.l + (W * (e - 1)) / (n - 1), yl = (v) => pad.t + H - (H * v) / maxLoss, ya = (v) => pad.t + H - H * Math.max(0, Math.min(1, v));
  const line = (key, y) => m.filter((p) => p[key] != null).map((p, i) => `${i ? "L" : "M"}${x(p.epoch).toFixed(1)},${y(Number(p[key])).toFixed(1)}`).join(" ");
  const step = Math.max(1, Math.ceil(n / 10));
  if (!m.length) return <div data-testid="train-chart-empty" style={{ padding: "24px 0", opacity: 0.7 }}>No epochs completed yet.</div>;
  return (
    <figure style={{ margin: 0 }} data-testid="train-chart">
      <svg role="img" aria-label={`Training loss and accuracy per epoch, ${m.length} epochs`} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", maxWidth: width, height: "auto", font: "11px sans-serif" }}>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => <g key={t}><line x1={pad.l} x2={pad.l + W} y1={ya(t)} y2={ya(t)} stroke={C.grid} strokeWidth="1" /><text x={width - pad.r + 6} y={ya(t) + 4} fill="currentColor" opacity=".7">{Math.round(t * 100)}%</text></g>)}
        {[0, 0.5, 1].map((t) => <text key={t} x={pad.l - 6} y={yl(maxLoss * t) + 4} textAnchor="end" fill="currentColor" opacity=".7">{(maxLoss * t).toFixed(2)}</text>)}
        {Array.from({ length: n }, (_, i) => i + 1).filter((e) => e % step === 0 || e === 1).map((e) => <text key={e} x={x(e)} y={height - 10} textAnchor="middle" fill="currentColor" opacity=".7">{e}</text>)}
        <text x={pad.l + W / 2} y={height - 0} textAnchor="middle" fill="currentColor" opacity=".7">Epoch</text>
        <path d={line("loss", yl)} fill="none" stroke={C.loss} strokeWidth="2" strokeDasharray="5 3" />
        <path d={line("accuracy", ya)} fill="none" stroke={C.acc} strokeWidth="2" />
        {m.map((p) => <g key={p.epoch}>{p.loss != null && <circle cx={x(p.epoch)} cy={yl(Number(p.loss))} r="3" fill={C.loss} />}{p.accuracy != null && <circle cx={x(p.epoch)} cy={ya(Number(p.accuracy))} r="3" fill={C.acc} />}</g>)}
      </svg>
      <figcaption style={{ display: "flex", gap: 16, fontSize: 12, flexWrap: "wrap" }}>
        <span><b style={{ color: C.loss }}>- - -</b> Loss (left axis)</span><span><b style={{ color: C.acc }}>---</b> Training accuracy (right axis)</span>
        <span data-testid="train-chart-last">Last epoch {m[m.length - 1].epoch}: loss {num(m[m.length - 1].loss)}, accuracy {pct(m[m.length - 1].accuracy)}</span>
      </figcaption>
    </figure>
  );
}

export function TrainingProgress({ value = 0, status = "", label }) {
  const v = Math.round(Math.max(0, Math.min(1, value)) * 100), bad = status === "Failed", done = status === "Completed";
  return (
    <div data-testid="train-progress" style={{ width: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}><span>{label || status}</span><span>{v}%</span></div>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v} aria-label={label || "Training progress"} style={{ height: 10, borderRadius: 5, background: "rgba(128,128,128,.25)", overflow: "hidden" }}>
        <div style={{ width: `${v}%`, height: "100%", background: bad ? "#b91c1c" : done ? "#15803d" : "#1d4ed8", transition: "width .3s" }} />
      </div>
    </div>
  );
}

/** Held-out accuracy against the untrained baseline (majority class / random). */
export function HeldOutBars({ heldOut }) {
  if (!heldOut) return <div data-testid="heldout-empty" style={{ opacity: 0.7 }}>Held-out accuracy appears after training finishes.</div>;
  const rows = [["Trained head", heldOut.accuracy, C.acc], ["Baseline (no training)", heldOut.baseline, C.base]];
  const d = (heldOut.accuracy - heldOut.baseline) * 100;
  return (
    <div data-testid="heldout" style={{ display: "grid", gap: 8 }}>
      {rows.map(([l, v, c]) => (
        <div key={l}><div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}><span>{l}</span><b>{pct(v)}</b></div>
          <div style={{ height: 14, background: "rgba(128,128,128,.2)", borderRadius: 3 }}><div style={{ width: `${Math.max(0, Math.min(1, v || 0)) * 100}%`, height: "100%", background: c, borderRadius: 3 }} /></div></div>))}
      <div style={{ fontSize: 12 }} data-testid="heldout-delta">{d >= 0 ? "+" : ""}{d.toFixed(1)} points over baseline</div>
    </div>
  );
}

/** Class scores returned by "Try it": label -> score bars. */
export function ScoreBars({ scores }) {
  const e = Object.entries(scores || {}).sort((a, b) => b[1] - a[1]);
  return <div data-testid="try-scores" style={{ display: "grid", gap: 4 }}>{e.map(([k, v]) => (
    <div key={k} style={{ display: "grid", gridTemplateColumns: "120px 1fr 56px", gap: 8, alignItems: "center", fontSize: 12 }}>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{k}</span><div style={{ height: 8, background: "rgba(128,128,128,.2)", borderRadius: 3 }}><div style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%`, height: "100%", background: C.acc, borderRadius: 3 }} /></div><span>{pct(v)}</span></div>))}</div>;
}
