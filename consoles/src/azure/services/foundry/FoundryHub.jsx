/* Microsoft Foundry hub: the portal's AI "menu view" (captured B-view-...-cognitiveserviceshub-menuview).
 * Layout from the capture: title "Microsoft Foundry | <page>", a chip row, the left menu (Overview, All resources and the
 * collapsible All models agents & tools / Single-capability / Earlier-generation / Help groups), Overview with Overview+Dashboard
 * tabs. Every list page shows what the ARM wire really holds for that kind. */
import { useState } from "react";
import { Button, Link, Tab, TabList } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { navigate } from "../../../common/router.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph } from "../../kit/common.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const CHIPS = ["Browse all resources in this subscription", "Are any resources impacted by outages", "Filter resources by region"];
const KIND_LABEL = { AIServices: "Foundry", OpenAI: "Azure OpenAI", SpeechServices: "Speech service", TextAnalytics: "Language service",
  TextTranslation: "Translator", ContentSafety: "Content safety", ComputerVision: "Computer vision", AnomalyDetector: "Anomaly detector" };

// id -> {label, kinds (cognitive kinds) | search | none}. Group membership of the sub-pages is inferred (the capture never expanded the groups).
const PAGES = {
  foundry: { label: "Microsoft Foundry", kinds: ["AIServices"], glyph: "cognitiveservices" },
  openai: { label: "Azure OpenAI", kinds: ["OpenAI"], glyph: "cognitiveservices" },
  search: { label: "AI Search", search: true, glyph: "cognitiveservices" },
  ml: { label: "Machine Learning", none: "Machine Learning workspaces", chips: ["Get workload templates for ML workspaces"] },
  speech: { label: "Speech service", kinds: ["SpeechServices"] },
  language: { label: "Language service", kinds: ["TextAnalytics"] },
  translator: { label: "Translator", kinds: ["TextTranslation"] },
  safety: { label: "Content safety", kinds: ["ContentSafety"] },
  vision: { label: "Computer vision", kinds: ["ComputerVision"] },
  anomaly: { label: "Anomaly detector (classic)", kinds: ["AnomalyDetector"] },
};
export const PAGE_LABEL = { ...Object.fromEntries(Object.entries(PAGES).map(([k, v]) => [k, v.label])), all: "All resources", docs: "Documentation" };
const MENU = [
  { id: "overview", label: "Overview" },
  { id: "all", label: "All resources" },
  { group: "All models, agents & tools", items: ["foundry", "openai", "search", "ml"].map((id) => ({ id, label: PAGES[id].label })) },
  { group: "Single-capability", items: ["speech", "language", "translator", "safety", "vision"].map((id) => ({ id, label: PAGES[id].label })) },
  { group: "Earlier-generation", items: [{ id: "anomaly", label: PAGES.anomaly.label }] },
  { group: "Help", items: [{ id: "docs", label: "Documentation" }] },
];
const MODELS = [["GPT", "OpenAI"], ["Claude", "Anthropic"], ["MAI", "Microsoft"], ["DeepSeek", "DeepSeek"], ["Qwen", "Alibaba Cloud"], ["Grok", "xAI"], ["Kimi", "Moonshot"], ["Mistral", "Mistral AI"], ["FLUX", "Black Forest Labs"]];

function Overview({ total }) {
  const [tab, setTab] = useState("overview");
  return (
    <div className="vy-page" data-testid="foundry-overview">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)}>
        <Tab value="overview">Overview</Tab><Tab value="dashboard">Dashboard</Tab>
      </TabList>
      {tab === "overview" ? (
        <>
          <section className="vy-fdy-hero">
            <div>
              <div className="vy-fdy-eyebrow">Microsoft Foundry</div>
              <h2>Build production-ready AI from the model up</h2>
              <p>Leverage Microsoft Foundry to build intelligent applications and agents efficiently. Access an extensive collection of models from leading AI providers. Integrate seamlessly with your existing data and tools, ensuring comprehensive observability and robust security for all your projects.</p>
              <Button appearance="primary" onClick={() => navigate("cognitiveservices", "create")}>Create a Foundry resource</Button>{" "}
              <Button onClick={() => navigate("foundry", "all")}>View all resources</Button>
            </div>
            <div className="vy-fdy-models">{MODELS.map(([n, v]) => <div key={n}><b>{n}</b><span>{v}</span></div>)}</div>
          </section>
          <div className="vy-fdy-sechead"><h2>Discover Foundry capabilities</h2><Link href="#/foundry/foundry">Explore more on Foundry portal</Link></div>
          <div className="vy-fdy-cards">
            {[["Build agents", "Design, orchestrate, and observe single- and multi-agent systems. Prototype in the portal, then export to code with the Foundry SDK and Microsoft Agent Framework.", "Agent documentation"],
              ["Any model, your data & tools", "Choose from 11,000+ models and ground them in your data with built-in knowledge and tools. Swap models without rewriting your app.", "Model documentation"],
              ["Observability & trust", "Evaluate, monitor, and govern every agent with Microsoft Entra identity, content safety, customer-managed keys, and Azure Monitor observability.", "Observability documentation"]].map(([h, p, l]) => (
              <article key={h}><div className="vy-fdy-art" /><h3>{h}</h3><p>{p}</p><Link href="#/foundry/foundry">{l}</Link></article>
            ))}
          </div>
        </>
      ) : (
        <div data-testid="foundry-dashboard">
          <div className="vy-fdy-dashbar"><Button appearance="subtle" icon={<ArrowClockwise20Regular />}>Refresh</Button>
            <span>{total ? `${total} AI resource${total === 1 ? "" : "s"} found in your subscription.` : "No AI resources found in your subscriptions. Filters are not available."}</span></div>
          {["Alerts and service health", "Active resources by cost", "Accumulated costs"].map((t) => (
            <section className="vy-fdy-tile" key={t}><h3>{t}</h3><div className="vy-fdy-nodata"><b>No data to display</b><span>Change your filters by subscription, timespan, category, or more to see some data</span></div></section>
          ))}
        </div>
      )}
    </div>
  );
}

function ResourceList({ id }) {
  const sub = useSubscription();
  const page = id === "all" ? { label: "All resources", all: true } : PAGES[id];
  const { data, loading, error, reload } = useAsync(async () => {
    if (page.none) return [];
    const [accts, search] = await Promise.all([page.search ? [] : api.listAccounts(), page.search || page.all ? api.listSearch().catch(() => []) : []]);
    const rows = [...accts.filter((a) => page.all || page.kinds?.includes(a.kind)), ...search.map((s) => ({ ...s, kind: "Search" }))];
    return rows;
  }, [id, sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <div className="vy-page" data-testid="foundry-list">
      <BrowseGrid
        resourceName={page.label.toLowerCase()} items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => navigate("cognitiveservices", "create")} subscriptionLabel={subName} csvName={`foundry-${id}.csv`}
        pills={[{ key: "rg", label: "Resource group", value: (r) => r.resourceGroup }, { key: "loc", label: "Location", value: (r) => locationLabel(r.location) }]}
        columns={[
          { key: "name", label: "Name", render: (r) => (r.kind === "Search" ? r.name : <Link href={`#/cognitiveservices/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link>) },
          { key: "type", label: "Type", value: (r) => (r.kind === "Search" ? "AI Search" : KIND_LABEL[r.kind] || r.kind) },
          { key: "resourceGroup", label: "Resource group" },
          { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
          { key: "subscription", label: "Subscription", value: () => subName },
        ]}
        emptyAction={page.none ? <span>{page.none} are not simulated.</span> : <Link href="#/cognitiveservices/create">Create</Link>}
      />
    </div>
  );
}

export default function FoundryHub({ params = {} }) {
  const panel = params.panel || "overview";
  const sub = useSubscription();
  const { data } = useAsync(() => api.listAccounts().catch(() => []), [sub.id]);
  const page = panel === "overview" ? null : panel === "all" ? { label: "All resources" } : PAGES[panel] || { label: panel };
  const chips = page?.chips || (panel === "overview" ? [] : CHIPS);
  const title = page ? `Microsoft Foundry | ${page.label}` : "Microsoft Foundry";
  return (
    <ResourceBlade
      title={title} subtitle={page ? `Default Directory | Vyomi simulator (${sub.displayName || sub.id})` : "Default Directory"}
      glyph={<Glyph id="cognitiveservices" />} closeHref="#/" menu={MENU} active={panel} groupsClosed hrefFor={(id) => `#/foundry${id === "overview" ? "" : `/${id}`}`}
    >
      {chips.length > 0 && <div className="vy-fdy-chips">{chips.map((c) => <button key={c} type="button">{c}</button>)}</div>}
      {panel === "overview" ? <Overview total={(data || []).length} />
        : panel === "docs" ? <div className="vy-page"><p>Foundry documentation lives on learn.microsoft.com.</p></div>
        : <ResourceList id={panel} />}
    </ResourceBlade>
  );
}
