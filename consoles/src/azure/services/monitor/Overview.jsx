import { useEffect, useState } from "react";
import { Button, Tab, TabList } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listAlertRules } from "./api.js";
import { Loading } from "../../kit/common.jsx";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "tutorials", label: "Tutorials" },
];

export default function Overview() {
  const [rules, setRules] = useState(null);
  useEffect(() => { listAlertRules().then(setRules).catch(() => setRules([])); }, []);
  const [tab, setTab] = useState(TABS[0].id);

  return (
    <MonitorShell active="overview">
      <section className="vy-form-section">
        <h3>Insights</h3>
        <p>Full observability into your applications, infrastructure, and network — over Vyomi's real simulated inventory.</p>
        <Button appearance="primary" as="a" href="#/monitor/insightshub">View all insights</Button>
      </section>

      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Monitor overview">
        {TABS.map((t) => <Tab key={t.id} value={t.id}>{t.label}</Tab>)}
      </TabList>
      {tab === "overview" ? (
        <section className="vy-form-section">
          <h3>Detection, triage, and diagnosis</h3>
          <p>
            {rules === null ? <Loading /> : `${rules.length} alert rule${rules.length === 1 ? "" : "s"} configured.`}
          </p>
          <ul>
            <li><a href="#/monitor/alerts">Alerts</a> — metric and activity log alert rules, backed by your real resources.</li>
            <li><a href="#/monitor/activitylog">Activity log</a> — every control-plane write Vyomi performs, newest first.</li>
            <li><a href="#/monitor/autoscale">Autoscale</a> — capacity rules for scale sets and App Service plans.</li>
            <li><a href="#/monitor/metrics">Metrics</a> — explore your inventory by resource type and location.</li>
          </ul>
        </section>
      ) : (
        <section className="vy-form-section">
          <h3>Tutorials</h3>
          <p>Start with an alert rule so you hear about a problem before it becomes an outage: pick a resource, a signal, a threshold, and an action group.</p>
        </section>
      )}
    </MonitorShell>
  );
}
