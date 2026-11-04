/* Microsoft Defender for Cloud pages. Every number on these pages is computed by the
 * Microsoft.Security engine from the live ARM state (and each AKS cluster's Kubescape scan) and
 * read over the native wire — see api.js. */
import { useMemo, useState } from "react";
import {
  Badge, Link, Switch, Tab, TabList, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading, fmtDate } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import DefenderShell, { LABEL } from "./DefenderShell.jsx";
import * as api from "./api.js";

const SEV_COLOR = { High: "danger", Medium: "warning", Low: "informative" };
export const SeverityBadge = ({ s }) => <Badge appearance="tint" color={SEV_COLOR[s] || "subtle"}>{s || "-"}</Badge>;
const STATUS_COLOR = { Unhealthy: "danger", Healthy: "success", NotApplicable: "subtle", "Not applicable": "subtle" };
export const StatusBadge = ({ s }) => <Badge appearance="outline" color={STATUS_COLOR[s] || "subtle"}>{s === "NotApplicable" ? "Not applicable" : s}</Badge>;
const pct = (x) => `${Math.round((x || 0) * 100)}%`;

function Cmd({ onRefresh, children }) {
  return (
    <div className="vy-cmdbar" role="toolbar" aria-label="Defender commands">
      <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={onRefresh}>Refresh</ToolbarButton>
      {children}
    </div>
  );
}

/** Per-cluster Kubernetes scanner state (Kubescape) — so the page never implies findings it
 *  doesn't have. */
export function ScannerStatus({ scanners }) {
  if (!scanners?.length) return null;
  const label = { succeeded: "Scanned", running: "Scanning…", queued: "Scan queued", unavailable: "Scanner unavailable",
    failed: "Scan failed", "plan-off": "Containers plan off", never: "Not scanned yet" };
  return (
    <CapabilityContainer id="azure.defender.kubernetes" title="Kubernetes posture scanning (Kubescape)">
      <Table size="small" aria-label="Kubernetes scanners">
        <TableHeader><TableRow>
          <TableHeaderCell>Cluster</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Scanner</TableHeaderCell>
          <TableHeaderCell>Controls evaluated</TableHeaderCell><TableHeaderCell>Last scan</TableHeaderCell><TableHeaderCell>Details</TableHeaderCell>
        </TableRow></TableHeader>
        <TableBody>
          {scanners.map((s) => (
            <TableRow key={s.clusterId}>
              <TableCell><Link href={api.resourceHref(s.clusterId)}>{api.resourceName(s.clusterId)}</Link></TableCell>
              <TableCell>{label[s.status] || s.status}{s.stale ? " (objects changed since)" : ""}</TableCell>
              <TableCell>{s.engine || "-"}</TableCell>
              <TableCell>{s.status === "succeeded" || s.controlsEvaluated ? s.controlsEvaluated : "-"}</TableCell>
              <TableCell>{s.scannedAt ? fmtDate(s.scannedAt) : "-"}</TableCell>
              <TableCell style={{ maxWidth: 420 }}>{s.reason || (s.frameworks ? `Frameworks: ${s.frameworks.join(", ")}` : "")}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </CapabilityContainer>
  );
}

// ── Overview ──────────────────────────────────────────────────────────────────────────
export function Overview() {
  const sub = useSubscription();
  const d = useAsync(async () => {
    const [score, a, plans, resources] = await Promise.all([api.getSecureScore(), api.listAssessments(), api.listPricings(), api.listResources()]);
    return { score, a, plans, resources };
  }, []);
  let body;
  if (d.loading && !d.data) body = <Loading />;
  else if (d.error) body = <ErrorBar error={d.error} title="Failed to load Defender for Cloud" />;
  else {
    const { score, a, plans, resources } = d.data;
    const recs = api.groupRecommendations(a.value);
    const active = recs.filter((r) => r.unhealthy);
    const bySev = (s) => active.filter((r) => r.severity === s).length;
    const unhealthyRes = new Set(a.value.filter((x) => x.properties.status.code === "Unhealthy").map((x) => x.properties.resourceDetails.Id.toLowerCase()));
    const assessed = new Set(a.value.map((x) => x.properties.resourceDetails.Id.toLowerCase()));
    const on = plans.filter((p) => p.properties.pricingTier === "Standard");
    const sc = score.properties?.score || {};
    body = (
      <>
        <Cmd onRefresh={d.reload} />
        <div className="vy-tiles" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12, margin: "12px 0" }}>
          <CapabilityContainer id="azure.defender.secure_score" title="Secure score">
            <div style={{ fontSize: 34, fontWeight: 600, lineHeight: "44px" }} aria-label="Secure score percentage">{pct(sc.percentage)}</div>
            <KV label="Points" value={`${sc.current ?? 0} of ${sc.max ?? 0}`} />
            <Link href="#/defender/posture">Explore your security posture</Link>
          </CapabilityContainer>
          <CapabilityContainer id="azure.defender.recommendations" title="Recommendations">
            <div style={{ fontSize: 34, fontWeight: 600, lineHeight: "44px" }} aria-label="Active recommendations">{active.length}</div>
            <KV label="High severity" value={bySev("High")} /><KV label="Medium severity" value={bySev("Medium")} /><KV label="Low severity" value={bySev("Low")} />
            <Link href="#/defender/recommendations">View recommendations</Link>
          </CapabilityContainer>
          <CapabilityContainer id="azure.defender.inventory" title="Assessed resources">
            <div style={{ fontSize: 34, fontWeight: 600, lineHeight: "44px" }}>{assessed.size}</div>
            <KV label="Unhealthy" value={unhealthyRes.size} /><KV label="Resources in subscription" value={resources.length} />
            <Link href="#/defender/inventory">Open inventory</Link>
          </CapabilityContainer>
          <CapabilityContainer id="azure.defender.plans" title="Workload protections">
            <div style={{ fontSize: 34, fontWeight: 600, lineHeight: "44px" }}>{on.length}/{plans.length}</div>
            <KV label="Defender plans on" value={on.map((p) => api.PLAN_LABEL[p.name] || p.name).join(", ") || "None"} />
            <Link href={`#/defender/environment/${encodeURIComponent(sub.id)}`}>Manage Defender plans</Link>
          </CapabilityContainer>
        </div>
        <CapabilityContainer id="azure.defender.alerts" title="Security alerts" />
        <ScannerStatus scanners={a.scanners} />
      </>
    );
  }
  return <DefenderShell active="overview"><div className="vy-panel-title">Overview</div>{body}</DefenderShell>;
}

// ── Recommendations list ──────────────────────────────────────────────────────────────
export function Recommendations({ query = {} }) {
  const resource = query.resource || "";
  const d = useAsync(() => api.listAssessments(resource || undefined), [resource]);
  const rows = d.data ? api.groupRecommendations(d.data.value) : [];
  return (
    <DefenderShell active="recommendations">
      <div className="vy-panel-title">Recommendations</div>
      {resource && <InfoBar title="Filtered to one resource">Showing recommendations for <b>{api.resourceName(resource)}</b> ({api.typeLabel(api.resourceType(resource))}). <Link href="#/defender/recommendations">Show all</Link></InfoBar>}
      <CapabilityContainer id="azure.defender.recommendations" title="All recommendations">
        <BrowseGrid
          resourceName="recommendation" rowKey={(r) => r.name} items={rows} loading={d.loading} error={d.error} onRefresh={d.reload}
          csvName="recommendations.csv" filterPlaceholder="Search recommendations"
          pills={[
            { key: "severity", label: "Severity", value: (r) => r.severity },
            { key: "status", label: "Status", value: (r) => r.status },
            { key: "source", label: "Source", value: (r) => (r.kubescape ? "Kubescape" : "Vyomi rule engine") },
          ]}
          columns={[
            { key: "displayName", label: "Recommendation", render: (r) => <Link href={`#/defender/recommendations/${r.name}${resource ? `?resource=${encodeURIComponent(resource)}` : ""}`}>{r.displayName}</Link> },
            { key: "severity", label: "Risk level", render: (r) => <SeverityBadge s={r.severity} />, value: (r) => r.severity },
            { key: "affected", label: "Affected resources", value: (r) => `${r.unhealthy} of ${r.unhealthy + r.healthy}` },
            { key: "status", label: "Status", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status },
            { key: "control", label: "Security control", value: (r) => r.control },
            { key: "type", label: "Resource type", value: (r) => r.resourceTypes.map(api.typeLabel).join(", ") },
            { key: "source", label: "Source", value: (r) => (r.kubescape ? `Kubescape ${r.kubescape}` : "Vyomi rule engine") },
          ]}
        />
      </CapabilityContainer>
      {d.data && <ScannerStatus scanners={d.data.scanners} />}
    </DefenderShell>
  );
}

// ── Recommendation detail ─────────────────────────────────────────────────────────────
export function RecommendationDetail({ params, query = {} }) {
  const resource = query.resource || "";
  const [tab, setTab] = useState("Unhealthy");
  const d = useAsync(async () => {
    const all = await api.listAssessments(resource || undefined);
    const items = all.value.filter((a) => a.name === params.name);
    const subs = {};
    for (const a of items.filter((x) => x.properties.status.code === "Unhealthy" && x.properties.metadata?.kubescapeControlId)) {
      subs[a.id] = await api.listSubAssessments(a.id);
    }
    return { items, subs };
  }, [params.name, resource]);
  let body;
  if (d.loading && !d.data) body = <Loading />;
  else if (d.error) body = <ErrorBar error={d.error} title="Failed to load the recommendation" />;
  else if (!d.data.items.length) body = <InfoBar intent="warning" title="Recommendation not found">No resource is currently assessed by this recommendation. <Link href="#/defender/recommendations">Back to recommendations</Link></InfoBar>;
  else {
    const { items, subs } = d.data;
    const m = items[0].properties.metadata || {};
    const shown = items.filter((a) => a.properties.status.code === tab);
    const count = (c) => items.filter((a) => a.properties.status.code === c).length;
    body = (
      <>
        <Cmd onRefresh={d.reload} />
        <h2 style={{ margin: "8px 0" }}>{items[0].properties.displayName}</h2>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", margin: "8px 0 16px" }}>
          <KV label="Risk level" value={<SeverityBadge s={m.severity} />} />
          <KV label="Security control" value={m.securityControl} />
          <KV label="Resource type" value={[...new Set(items.map((a) => api.typeLabel(api.resourceType(a.properties.resourceDetails.Id))))].join(", ")} />
          {m.kubescapeControlId && <KV label="Kubescape control" value={m.kubescapeControlId} />}
          {m.frameworks?.length > 0 && <KV label="Frameworks" value={m.frameworks.join(", ")} />}
          <KV label="Freshness" value={m.kubescapeControlId ? "Each Kubescape scan of the cluster" : "Evaluated on every read"} />
        </div>
        <section className="vy-section"><h3>Description</h3><p style={{ fontSize: 13 }}>{m.description}</p></section>
        <section className="vy-section"><h3>Remediation steps</h3><p style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{m.remediationDescription || "-"}</p></section>
        <section className="vy-section">
          <h3>Affected resources</h3>
          <TabList selectedValue={tab} onTabSelect={(_, x) => setTab(x.value)} aria-label="Affected resources">
            <Tab value="Unhealthy">Unhealthy resources ({count("Unhealthy")})</Tab>
            <Tab value="Healthy">Healthy resources ({count("Healthy")})</Tab>
            <Tab value="NotApplicable">Not applicable resources ({count("NotApplicable")})</Tab>
          </TabList>
          <Table size="small" aria-label={`${tab} resources`} style={{ marginTop: 8 }}>
            <TableHeader><TableRow>
              <TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Resource group</TableHeaderCell>
              <TableHeaderCell>Resource type</TableHeaderCell><TableHeaderCell>Status details</TableHeaderCell>
            </TableRow></TableHeader>
            <TableBody>
              {shown.length === 0 && <TableRow><TableCell colSpan={4}>No resources.</TableCell></TableRow>}
              {shown.map((a) => {
                const rid = a.properties.resourceDetails.Id;
                const h = api.resourceHref(rid);
                return (
                  <TableRow key={a.id}>
                    <TableCell>{h ? <Link href={h}>{api.resourceName(rid)}</Link> : api.resourceName(rid)}</TableCell>
                    <TableCell>{api.resourceGroup(rid)}</TableCell>
                    <TableCell>{api.typeLabel(api.resourceType(rid))}</TableCell>
                    <TableCell>{a.properties.status.description || (a.properties.status.code === "Healthy" ? "Healthy" : "-")}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </section>
        {tab === "Unhealthy" && Object.entries(subs).map(([aid, list]) => (
          <section className="vy-section" key={aid}>
            <h3>Kubernetes objects failing in {api.resourceName(items.find((a) => a.id === aid).properties.resourceDetails.Id)}</h3>
            <Table size="small" aria-label="Failing Kubernetes objects">
              <TableHeader><TableRow>
                <TableHeaderCell>Kind</TableHeaderCell><TableHeaderCell>Namespace</TableHeaderCell><TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Fix / failing paths</TableHeaderCell><TableHeaderCell>Related objects</TableHeaderCell>
              </TableRow></TableHeader>
              <TableBody>
                {list.map((s) => {
                  const ad = s.properties.additionalData || {};
                  const paths = [...(ad.fixPaths || []).map((p) => `${p.path}${p.value !== undefined && p.value !== "" ? ` = ${p.value}` : ""}`), ...(ad.failedPaths || []), ...(ad.reviewPaths || [])];
                  return (
                    <TableRow key={s.id}>
                      <TableCell>{ad.kind}</TableCell><TableCell>{ad.namespace || "-"}</TableCell><TableCell>{ad.name}</TableCell>
                      <TableCell style={{ fontFamily: "monospace", fontSize: 12 }}>{paths.length ? paths.join("; ") : "-"}</TableCell>
                      <TableCell>{(ad.relatedObjects || []).join(", ") || "-"}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </section>
        ))}
      </>
    );
  }
  return <DefenderShell active="recommendations"><div className="vy-panel-title"><Link href="#/defender/recommendations">Recommendations</Link></div>{body}</DefenderShell>;
}

// ── Inventory ─────────────────────────────────────────────────────────────────────────
export function Inventory() {
  const d = useAsync(async () => {
    const [resources, a] = await Promise.all([api.listResources(), api.listAssessments()]);
    return { resources, a };
  }, []);
  const rows = useMemo(() => {
    if (!d.data) return [];
    const by = {};
    for (const x of d.data.a.value) {
      const k = x.properties.resourceDetails.Id.toLowerCase();
      (by[k] ||= { un: 0, total: 0 });
      by[k].total += 1;
      if (x.properties.status.code === "Unhealthy") by[k].un += 1;
    }
    return d.data.resources.map((r) => ({ ...r, un: by[r.id.toLowerCase()]?.un || 0, assessed: !!by[r.id.toLowerCase()] }));
  }, [d.data]);
  return (
    <DefenderShell active="inventory">
      <div className="vy-panel-title">Inventory</div>
      <CapabilityContainer id="azure.defender.inventory" title="Resources">
        <BrowseGrid
          resourceName="resource" items={rows} loading={d.loading} error={d.error} onRefresh={d.reload} csvName="inventory.csv"
          pills={[{ key: "type", label: "Resource type", value: (r) => api.typeLabel(r.type) }, { key: "health", label: "Health", value: (r) => (!r.assessed ? "Not assessed" : r.un ? "Unhealthy" : "Healthy") }]}
          columns={[
            { key: "name", label: "Resource name", render: (r) => (api.resourceHref(r.id) ? <Link href={api.resourceHref(r.id)}>{r.name}</Link> : r.name) },
            { key: "type", label: "Resource type", value: (r) => api.typeLabel(r.type) },
            { key: "rg", label: "Resource group", value: (r) => api.resourceGroup(r.id) },
            { key: "un", label: "Recommendations", render: (r) => (r.assessed ? <Link href={`#/defender/recommendations?resource=${encodeURIComponent(r.id)}`}>{r.un} unhealthy</Link> : "Not assessed"), value: (r) => r.un },
          ]}
        />
      </CapabilityContainer>
    </DefenderShell>
  );
}

// ── Security posture (secure score by control) ────────────────────────────────────────
export function Posture() {
  const d = useAsync(async () => ({ score: await api.getSecureScore(), controls: await api.listSecureScoreControls() }), []);
  let body;
  if (d.loading && !d.data) body = <Loading />;
  else if (d.error) body = <ErrorBar error={d.error} title="Failed to load the secure score" />;
  else {
    const sc = d.data.score.properties?.score || {};
    body = (
      <>
        <Cmd onRefresh={d.reload} />
        <CapabilityContainer id="azure.defender.secure_score" title="Secure score">
          <div style={{ fontSize: 34, fontWeight: 600, lineHeight: "44px" }}>{pct(sc.percentage)}</div>
          <KV label="Points" value={`${sc.current} of ${sc.max}`} />
          <Table size="small" aria-label="Security controls" style={{ marginTop: 12 }}>
            <TableHeader><TableRow>
              <TableHeaderCell>Security control</TableHeaderCell><TableHeaderCell>Max score</TableHeaderCell><TableHeaderCell>Current score</TableHeaderCell>
              <TableHeaderCell>Potential increase</TableHeaderCell><TableHeaderCell>Unhealthy resources</TableHeaderCell><TableHeaderCell>Healthy resources</TableHeaderCell>
            </TableRow></TableHeader>
            <TableBody>
              {d.data.controls.map((c) => {
                const p = c.properties, inc = sc.max ? (p.score.max - p.score.current) / sc.max : 0;
                return (
                  <TableRow key={c.name}>
                    <TableCell>{p.displayName}</TableCell><TableCell>{p.score.max}</TableCell><TableCell>{p.score.current}</TableCell>
                    <TableCell>+{pct(inc)}</TableCell><TableCell>{p.unhealthyResourceCount}</TableCell><TableCell>{p.healthyResourceCount}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CapabilityContainer>
      </>
    );
  }
  return <DefenderShell active="posture"><div className="vy-panel-title">Security posture</div>{body}</DefenderShell>;
}

// ── Regulatory compliance (Kubescape frameworks per cluster) ─────────────────────────
export function Compliance() {
  const d = useAsync(() => api.listAssessments(), []);
  const scanned = (d.data?.scanners || []).filter((s) => s.frameworkScores && Object.keys(s.frameworkScores).length);
  return (
    <DefenderShell active="compliance">
      <div className="vy-panel-title">Regulatory compliance</div>
      {d.loading && !d.data ? <Loading /> : d.error ? <ErrorBar error={d.error} /> : (
        <CapabilityContainer id="azure.defender.compliance" title="Kubernetes frameworks (Kubescape)">
          {scanned.length === 0 ? <p style={{ fontSize: 13 }}>No cluster has a completed Kubescape scan yet — turn on the Containers plan and apply objects to a cluster.</p> : (
            <Table size="small" aria-label="Framework compliance">
              <TableHeader><TableRow><TableHeaderCell>Cluster</TableHeaderCell><TableHeaderCell>Framework</TableHeaderCell><TableHeaderCell>Compliance score</TableHeaderCell><TableHeaderCell>Scanned</TableHeaderCell></TableRow></TableHeader>
              <TableBody>
                {scanned.flatMap((s) => Object.entries(s.frameworkScores).map(([fw, v]) => (
                  <TableRow key={s.clusterId + fw}>
                    <TableCell>{api.resourceName(s.clusterId)}</TableCell><TableCell>{fw}</TableCell>
                    <TableCell>{v === null || v === undefined ? "-" : `${Math.round(v)}%`}</TableCell><TableCell>{fmtDate(s.scannedAt)}</TableCell>
                  </TableRow>
                )))}
              </TableBody>
            </Table>
          )}
        </CapabilityContainer>
      )}
    </DefenderShell>
  );
}

// ── Environment settings → Defender plans ─────────────────────────────────────────────
export function Environment() {
  const sub = useSubscription();
  return (
    <DefenderShell active="environment">
      <div className="vy-panel-title">Environment settings</div>
      <Table size="small" aria-label="Environments">
        <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Subscription ID</TableHeaderCell></TableRow></TableHeader>
        <TableBody><TableRow>
          <TableCell><Link href={`#/defender/environment/${encodeURIComponent(sub.id)}`}>{sub.displayName || sub.id}</Link></TableCell>
          <TableCell>Subscription</TableCell><TableCell>{sub.id}</TableCell>
        </TableRow></TableBody>
      </Table>
    </DefenderShell>
  );
}

export function DefenderPlans({ params }) {
  const notify = useNotify();
  const d = useAsync(() => api.listPricings(), []);
  const [edit, setEdit] = useState({});
  const [busy, setBusy] = useState(false);
  const tier = (p) => edit[p.name] ?? p.properties.pricingTier;
  const dirty = d.data ? d.data.filter((p) => tier(p) !== p.properties.pricingTier) : [];
  const save = async () => {
    setBusy(true);
    try {
      for (const p of dirty) await api.setPricing(p.name, tier(p));
      notify.success(`Saved ${dirty.length} Defender plan change${dirty.length === 1 ? "" : "s"}.`, "Defender plans updated");
      setEdit({}); d.reload();
    } catch (e) { notify.error(e, "Failed to update Defender plans"); }
    finally { setBusy(false); }
  };
  return (
    <DefenderShell active="environment">
      <div className="vy-panel-title">Settings | Defender plans</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Defender plans commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty.length || busy} onClick={save}>Save</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { setEdit({}); d.reload(); }}>Refresh</ToolbarButton>
      </div>
      <KV label="Subscription" value={params.sub} />
      <CapabilityContainer id="azure.defender.plans" title="Cloud Workload Protection (CWP)">
        {d.loading && !d.data ? <Loading /> : d.error ? <ErrorBar error={d.error} /> : (
          <Table size="small" aria-label="Defender plans">
            <TableHeader><TableRow><TableHeaderCell>Plan</TableHeaderCell><TableHeaderCell>Pricing tier</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Enabled since</TableHeaderCell></TableRow></TableHeader>
            <TableBody>
              {d.data.map((p) => (
                <TableRow key={p.name}>
                  <TableCell>{api.PLAN_LABEL[p.name] || p.name}</TableCell>
                  <TableCell>{tier(p) === "Standard" ? "Standard" : "Free"}</TableCell>
                  <TableCell>
                    <Switch checked={tier(p) === "Standard"} label={tier(p) === "Standard" ? "On" : "Off"} aria-label={`${api.PLAN_LABEL[p.name] || p.name} plan`}
                      onChange={(_, x) => setEdit((e) => ({ ...e, [p.name]: x.checked ? "Standard" : "Free" }))} />
                  </TableCell>
                  <TableCell>{p.properties.enablementTime ? fmtDate(p.properties.enablementTime) : "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CapabilityContainer>
    </DefenderShell>
  );
}

// ── Security alerts (honest) + every other not-simulated menu item ────────────────────
export function Alerts() {
  return (
    <DefenderShell active="alerts">
      <div className="vy-panel-title">Security alerts</div>
      <CapabilityContainer id="azure.defender.alerts" title="Security alerts" />
    </DefenderShell>
  );
}

export function NotSimulatedPanel({ params }) {
  const id = params.panel;
  return (
    <DefenderShell active={id}>
      <div className="vy-panel-title">{LABEL[id] || id}</div>
      <CapabilityContainer id="azure.defender.other" title={LABEL[id] || id} />
    </DefenderShell>
  );
}

// ── Embedded in a resource's own blade ("Microsoft Defender for Cloud" menu item) ────
export function ResourceRecommendations({ resourceId }) {
  const d = useAsync(() => api.listAssessments(resourceId), [resourceId]);
  const rows = d.data ? api.groupRecommendations(d.data.value) : [];
  return (
    <>
      <div className="vy-panel-title">Microsoft Defender for Cloud</div>
      <Cmd onRefresh={d.reload}>
        <ToolbarButton as="a" href={`#/defender/recommendations?resource=${encodeURIComponent(resourceId)}`}>View all recommendations in Defender for Cloud</ToolbarButton>
      </Cmd>
      <CapabilityContainer id="azure.defender.recommendations" title="Recommendations">
        {d.loading && !d.data ? <Loading /> : d.error ? <ErrorBar error={d.error} /> : (
          <Table size="small" aria-label="Resource recommendations">
            <TableHeader><TableRow><TableHeaderCell>Recommendation</TableHeaderCell><TableHeaderCell>Risk level</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Details</TableHeaderCell></TableRow></TableHeader>
            <TableBody>
              {rows.length === 0 && <TableRow><TableCell colSpan={4}>No recommendations assess this resource.</TableCell></TableRow>}
              {rows.map((r) => (
                <TableRow key={r.name}>
                  <TableCell><Link href={`#/defender/recommendations/${r.name}?resource=${encodeURIComponent(resourceId)}`}>{r.displayName}</Link></TableCell>
                  <TableCell><SeverityBadge s={r.severity} /></TableCell>
                  <TableCell><StatusBadge s={r.status} /></TableCell>
                  <TableCell>{r.items[0]?.properties.status.description || ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CapabilityContainer>
      {d.data && <ScannerStatus scanners={d.data.scanners} />}
    </>
  );
}

