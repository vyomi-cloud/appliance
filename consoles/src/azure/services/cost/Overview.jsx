import { useEffect, useState } from "react";
import { Button, Tab, TabList } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { getSubscriptionInfo } from "../../kit/arm.js";
import { Loading } from "../../kit/common.jsx";

const TABS = [
  { id: "get-started", label: "Get Started", body: "Analyze your Azure spend, forecast future costs, and set budgets to keep spending under control — all backed by Vyomi's real resource inventory." },
  { id: "tutorials", label: "Tutorials", body: "Start with Cost analysis to see where you're spending, then set a Budget with alerts so you hear about overspend before the bill arrives." },
  { id: "whats-new", label: "What's new", body: "Budgets now show evaluated spend and a forecast computed live from your resources, and Cost alerts are raised automatically when a budget crosses its threshold." },
];

export default function Overview() {
  const [sub, setSub] = useState(null);
  useEffect(() => { getSubscriptionInfo().then(setSub).catch(() => setSub(false)); }, []);
  const [tab, setTab] = useState(TABS[0].id);
  const panel = TABS.find((t) => t.id === tab);

  return (
    <CostShell active="overview">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>Scope</h3>
          <div className="vy-kv"><span>Scope</span><span>{sub === null ? "Loading..." : sub ? sub.displayName : "--"} <a href="#/cost/changescope">Change</a></span></div>
        </section>

        <section className="vy-form-section">
          <h3>Analyze and optimize cloud costs</h3>
          <p>Cost Management gives you the tools to monitor, allocate, and optimize your Azure costs — over Vyomi's real simulated inventory, not sample data.</p>
        </section>

        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Cost Management overview">
          {TABS.map((t) => <Tab key={t.id} value={t.id}>{t.label}</Tab>)}
        </TabList>
        <div style={{ padding: "12px 0" }}>{panel.body}</div>

        <div className="vy-cards" style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(3, 1fr)", marginTop: 16 }}>
          <section className="vy-form-section">
            <h3>Setup your account</h3>
            <p>Review your subscription scope and preferences.</p>
            <Button appearance="primary" as="a" href="#/cost/configuration">Configure</Button>
          </section>
          <section className="vy-form-section">
            <h3>Report on and analyze trends</h3>
            <p>Break down spend by service, location, and resource group.</p>
            <Button appearance="primary" as="a" href="#/cost/analysis">Analyze costs</Button>
          </section>
          <section className="vy-form-section">
            <h3>Control and optimize costs</h3>
            <p>See where your real inventory is spending the most.</p>
            <Button appearance="primary" as="a" href="#/cost/advisor">View recommendations</Button>
          </section>
        </div>
        {sub === null && <Loading />}
      </div>
    </CostShell>
  );
}
