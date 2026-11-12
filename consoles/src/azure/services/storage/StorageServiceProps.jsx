/* Queue / Table service properties on the DATA plane (Get/Set Service Properties): logging, hour/minute metrics, retention.
 * Enforced by core/azure_storage_svc_core.py: requests are counted into the metrics and logged per these flags; CORS rules
 * (above, via ARM) are evaluated on preflight. Logs / metrics are an in-memory ring (not the $logs container / $Metrics tables). */
import { useState } from "react";
import { Button, Checkbox, Field, Input } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { sendRaw } from "../../../common/wire.js";
import { ErrorBar, InfoBar, KV, Loading } from "../../kit/common.jsx";

const hdr = (kind, a) => ({ "x-vyomi-service": kind, "x-vyomi-account": a.name, "x-ms-version": "2021-08-06", "content-type": "application/xml" });
const tx = (el, t) => el?.getElementsByTagName(t)[0]?.textContent;
const parse = (xml) => {
  const d = new DOMParser().parseFromString(xml, "application/xml");
  const sect = (n) => d.getElementsByTagName(n)[0];
  const ret = (e) => (tx(e, "Enabled") === "true" ? tx(e, "Days") || "" : "");
  const lg = sect("Logging"), hm = sect("HourMetrics"), mm = sect("MinuteMetrics");
  return {
    read: tx(lg, "Read") === "true", write: tx(lg, "Write") === "true", del: tx(lg, "Delete") === "true", logDays: ret(lg),
    hourOn: tx(hm, "Enabled") === "true", hourApis: tx(hm, "IncludeAPIs") === "true", hourDays: ret(hm),
    minOn: tx(mm, "Enabled") === "true", minApis: tx(mm, "IncludeAPIs") === "true", minDays: ret(mm),
  };
};
const pol = (days) => `<RetentionPolicy><Enabled>${days ? "true" : "false"}</Enabled>${days ? `<Days>${days}</Days>` : ""}</RetentionPolicy>`;
const met = (tag, on, apis, days) => `<${tag}><Version>1.0</Version><Enabled>${on}</Enabled>${on ? `<IncludeAPIs>${apis}</IncludeAPIs>` : ""}${pol(days)}</${tag}>`;
const toXml = (p) => `<?xml version="1.0" encoding="utf-8"?><StorageServiceProperties><Logging><Version>1.0</Version><Read>${p.read}</Read><Write>${p.write}</Write><Delete>${p.del}</Delete>${pol(p.logDays)}</Logging>${met("HourMetrics", p.hourOn, p.hourApis, p.hourDays)}${met("MinuteMetrics", p.minOn, p.minApis, p.minDays)}</StorageServiceProperties>`;

export function ServiceMonitoring({ a, kind }) {
  const notify = useNotify();
  const h = hdr(kind, a);
  const cur = useAsync(async () => {
    const r = await sendRaw("GET", "/", { headers: h, query: { restype: "service", comp: "properties" } });
    if (!r.ok) throw new Error(r.text || `HTTP ${r.status}`);
    const logs = JSON.parse((await sendRaw("GET", "/", { headers: h, query: { restype: "service", comp: "vyomi-logs" } })).text || "{}").value || [];
    const metrics = JSON.parse((await sendRaw("GET", "/", { headers: h, query: { restype: "service", comp: "vyomi-metrics" } })).text || "{}").value || [];
    return { p: parse(r.text), logs, metrics };
  }, [a.id, kind]);
  const [edit, setEdit] = useState(null);
  const p = edit || cur.data?.p;
  const set = (k, v) => setEdit({ ...(p || {}), [k]: v });
  const save = async () => {
    const r = await sendRaw("PUT", "/", { headers: h, query: { restype: "service", comp: "properties" }, body: toXml(p) });
    if (r.ok) { notify.success("Service properties saved.", "Saved"); setEdit(null); cur.reload(); } else notify.error(new Error(r.text || `HTTP ${r.status}`), "Saving failed");
  };
  const totals = (cur.data?.metrics || []).filter((m) => m.api === null);
  return (
    <div style={{ marginTop: 12 }}>
      <h3>Logging and metrics</h3>
      <ErrorBar error={cur.error} />
      <InfoBar>Enforced by the data plane: requests are counted into the metrics and logged per these flags, old entries are purged after the retention days. Entries are shown here from an in-memory ring (real Azure writes the $logs container / $Metrics tables).</InfoBar>
      {cur.loading && !cur.data ? <Loading /> : p && (
        <>
          <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
            <strong>Logging</strong>
            <Checkbox checked={p.read} onChange={(_, d) => set("read", !!d.checked)} label="Read" />
            <Checkbox checked={p.write} onChange={(_, d) => set("write", !!d.checked)} label="Write" />
            <Checkbox checked={p.del} onChange={(_, d) => set("del", !!d.checked)} label="Delete" />
            <Field label="Retention (days, empty = keep)"><Input value={p.logDays} onChange={(_, d) => set("logDays", d.value)} aria-label="Logging retention days" /></Field>
          </div>
          <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
            <strong>Hour metrics</strong>
            <Checkbox checked={p.hourOn} onChange={(_, d) => set("hourOn", !!d.checked)} label="Enabled" />
            <Checkbox checked={p.hourApis} disabled={!p.hourOn} onChange={(_, d) => set("hourApis", !!d.checked)} label="Include APIs" />
            <Field label="Retention (days)"><Input value={p.hourDays} onChange={(_, d) => set("hourDays", d.value)} aria-label="Hour metrics retention days" /></Field>
          </div>
          <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
            <strong>Minute metrics</strong>
            <Checkbox checked={p.minOn} onChange={(_, d) => set("minOn", !!d.checked)} label="Enabled" />
            <Checkbox checked={p.minApis} disabled={!p.minOn} onChange={(_, d) => set("minApis", !!d.checked)} label="Include APIs" />
            <Field label="Retention (days)"><Input value={p.minDays} onChange={(_, d) => set("minDays", d.value)} aria-label="Minute metrics retention days" /></Field>
          </div>
          <div style={{ marginTop: 8 }}><Button appearance="primary" onClick={save} aria-label="Save service properties">Save</Button> <Button onClick={() => cur.reload()}>Refresh</Button></div>
          <KV label="Log entries recorded" value={String(cur.data.logs.length)} />
          <KV label="Metric intervals recorded" value={String(totals.length)} />
          <KV label="Requests counted" value={String(totals.reduce((n, m) => n + m.TotalRequests, 0))} />
        </>
      )}
    </div>
  );
}
