import { useEffect, useState } from "react";
import { Button, Checkbox, Input, Select, Textarea } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular } from "@fluentui/react-icons";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { getSubscriptionInfo, listResourceGroups } from "../../kit/arm.js";
import { listActionGroups, listAllResources, putMetricAlert, SEVERITY_LABEL } from "./api.js";

const SIGNALS = ["Percentage CPU", "Available Memory Bytes", "Network In Total", "Network Out Total", "Disk Read Bytes"];
const AGGREGATIONS = ["Average", "Count", "Minimum", "Maximum", "Total"];
const OPERATORS = { "Greater than": "GreaterThan", "Greater than or equal to": "GreaterThanOrEqual", "Less than": "LessThan", "Less than or equal to": "LessThanOrEqual" };
const CHECK_EVERY = { PT1M: "1 minute", PT5M: "5 minutes", PT15M: "15 minutes", PT30M: "30 minutes", PT1H: "1 hour" };
const LOOKBACK = { PT5M: "5 minutes", PT15M: "15 minutes", PT30M: "30 minutes", PT1H: "1 hour", PT6H: "6 hours", PT12H: "12 hours", P1D: "1 day" };

export default function CreateMetricAlert() {
  const [resources, setResources] = useState([]);
  const [scope, setScope] = useState("");
  const [signal, setSignal] = useState(SIGNALS[0]);
  const [threshold, setThreshold] = useState("Static");
  const [aggregation, setAggregation] = useState("Average");
  const [operator, setOperator] = useState("Greater than");
  const [thresholdValue, setThresholdValue] = useState("80");
  const [checkEvery, setCheckEvery] = useState("PT1M");
  const [lookback, setLookback] = useState("PT5M");
  const [actionGroups, setActionGroups] = useState([]);
  const [selectedGroups, setSelectedGroups] = useState(new Set());
  const [sub, setSub] = useState(null);
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [severity, setSeverity] = useState("3");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enableNow, setEnableNow] = useState(true);
  const [autoResolve, setAutoResolve] = useState(true);
  const [tags, setTags] = useState([{ name: "", value: "" }]);

  useEffect(() => {
    listAllResources().then((r) => { setResources(r); setScope(r[0]?.id || ""); }).catch(() => setResources([]));
    listActionGroups().then(setActionGroups).catch(() => setActionGroups([]));
    getSubscriptionInfo().then(setSub).catch(() => setSub(false));
    listResourceGroups().then(setRgs).catch(() => setRgs([]));
  }, []);

  const toggleGroup = (id) => setSelectedGroups((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const resource = resources.find((r) => r.id === scope);

  const scopeTab = (
    <FormSection title="Select a resource" description="Choose the resource this alert rule monitors.">
      <FormRow label="Resource" required>
        {resources.length ? (
          <Select value={scope} onChange={(_, d) => setScope(d.value)} aria-label="Resource">
            {resources.map((r) => <option key={r.id} value={r.id}>{r.name} — {r.typeLabel} — {r.location}</option>)}
          </Select>
        ) : <p>No resources yet — create one first, then come back to scope this alert rule to it.</p>}
      </FormRow>
    </FormSection>
  );

  const conditionTab = (
    <FormSection title="Condition">
      <FormRow label="Signal name" required>
        <Select value={signal} onChange={(_, d) => setSignal(d.value)} aria-label="Signal name">{SIGNALS.map((s) => <option key={s}>{s}</option>)}</Select>
      </FormRow>
      <FormRow label="Threshold">
        <Select value={threshold} onChange={(_, d) => setThreshold(d.value)} aria-label="Threshold"><option>Static</option><option>Dynamic</option></Select>
      </FormRow>
      <FormRow label="Aggregation type">
        <Select value={aggregation} onChange={(_, d) => setAggregation(d.value)} aria-label="Aggregation type">{AGGREGATIONS.map((a) => <option key={a}>{a}</option>)}</Select>
      </FormRow>
      <FormRow label="Operator">
        <Select value={operator} onChange={(_, d) => setOperator(d.value)} aria-label="Operator">{Object.keys(OPERATORS).map((o) => <option key={o}>{o}</option>)}</Select>
      </FormRow>
      <FormRow label="Threshold value" required><Input type="number" value={thresholdValue} onChange={(_, d) => setThresholdValue(d.value)} aria-label="Threshold value" /></FormRow>
      <FormRow label="Check every">
        <Select value={checkEvery} onChange={(_, d) => setCheckEvery(d.value)} aria-label="Check every">{Object.entries(CHECK_EVERY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
      </FormRow>
      <FormRow label="Lookback period">
        <Select value={lookback} onChange={(_, d) => setLookback(d.value)} aria-label="Lookback period">{Object.entries(LOOKBACK).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
      </FormRow>
    </FormSection>
  );

  const actionsTab = (
    <FormSection title="Actions">
      <FormRow label="Action groups" info="Notified when the rule's condition is met.">
        {actionGroups.length ? actionGroups.map((g) => (
          <div key={g.id}><Checkbox label={`${g.name} (${g.properties.groupShortName})`} checked={selectedGroups.has(g.id)} onChange={() => toggleGroup(g.id)} /></div>
        )) : <p>No action groups yet. <a href="#/monitor/createactiongroup">Create action group</a></p>}
      </FormRow>
    </FormSection>
  );

  const detailsTab = (
    <>
      <FormSection title="Project details">
        <FormRow label="Subscription" required><Input readOnly value={sub === null ? "Loading..." : sub ? sub.displayName : "Select a subscription"} aria-label="Subscription" /></FormRow>
        <FormRow label="Resource group" required>
          <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
            <option value="cloudlearn-rg">cloudlearn-rg</option>
            {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Alert rule details">
        <FormRow label="Severity">
          <Select value={severity} onChange={(_, d) => setSeverity(d.value)} aria-label="Severity">
            {Object.entries(SEVERITY_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Alert rule name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Alert rule name" /></FormRow>
        <FormRow label="Alert rule description"><Textarea value={description} onChange={(_, d) => setDescription(d.value)} aria-label="Alert rule description" /></FormRow>
      </FormSection>
      <FormSection title="Advanced options">
        <FormRow label="Enable upon creation"><Checkbox checked={enableNow} onChange={(_, d) => setEnableNow(d.checked)} /></FormRow>
        <FormRow label="Automatically resolve alerts"><Checkbox checked={autoResolve} onChange={(_, d) => setAutoResolve(d.checked)} /></FormRow>
      </FormSection>
    </>
  );

  const update = (i, patch) => setTags(tags.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const tagsTab = (
    <FormSection title="Tags">
      <p style={{ fontSize: 12 }}>Name/value pairs to categorize resources and view consolidated billing.</p>
      <FormRow label="Tags">
        <div>
          {tags.map((t, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4 }}>
              <Input placeholder="Name" value={t.name} onChange={(_, d) => update(i, { name: d.value })} aria-label="Tag name" />
              <Input placeholder="Value" value={t.value} onChange={(_, d) => update(i, { value: d.value })} aria-label="Tag value" />
              <Button icon={<Delete20Regular />} appearance="subtle" aria-label="Remove tag" onClick={() => setTags(tags.filter((_, j) => j !== i))} />
            </div>
          ))}
          <Button icon={<Add20Regular />} onClick={() => setTags([...tags, { name: "", value: "" }])}>Add tag</Button>
        </div>
      </FormRow>
    </FormSection>
  );

  const body = () => ({
    location: "global",
    tags: Object.fromEntries(tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      description, severity: Number(severity), enabled: enableNow, scopes: [scope],
      evaluationFrequency: checkEvery, windowSize: lookback,
      criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", allOf: [
        { criterionType: "StaticThresholdCriterion", name: "Metric1", metricName: signal, operator: OPERATORS[operator], timeAggregation: aggregation, threshold: Number(thresholdValue) },
      ] },
      autoMitigate: autoResolve,
      actions: [...selectedGroups].map((id) => ({ actionGroupId: id })),
    },
  });

  return (
    <CreateWizard title="Create an alert rule" closeHref="#/monitor/alerts" glyph={<Glyph id="monitor" size={32} />}
      tabs={[
        { id: "scope", label: "Scope", content: scopeTab, validate: () => (scope ? [] : ["Select a resource."]) },
        { id: "condition", label: "Condition", content: conditionTab, validate: () => (thresholdValue !== "" ? [] : ["Threshold value is required."]) },
        { id: "actions", label: "Actions", content: actionsTab },
        { id: "details", label: "Details", content: detailsTab, validate: () => (name ? [] : ["Alert rule name is required."]) },
        { id: "tags", label: "Tags", content: tagsTab },
      ]}
      review={() => (
        <>
          <FormSection title="Scope"><FormRow label="Resource"><span>{resource ? `${resource.name} (${resource.typeLabel})` : "--"}</span></FormRow></FormSection>
          <FormSection title="Condition"><FormRow label="Condition"><span>{signal} {operator.toLowerCase()} {thresholdValue} (avg {aggregation.toLowerCase()} over {CHECK_EVERY[checkEvery]})</span></FormRow></FormSection>
          <FormSection title="Actions"><FormRow label="Action groups"><span>{selectedGroups.size} selected</span></FormRow></FormSection>
          <FormSection title="Details">
            <FormRow label="Severity"><span>{SEVERITY_LABEL[severity]}</span></FormRow>
            <FormRow label="Name"><span>{name}</span></FormRow>
            <FormRow label="Resource group"><span>{rg}</span></FormRow>
          </FormSection>
        </>
      )}
      onCreate={async () => { await putMetricAlert(rg, name, body()); location.hash = "#/monitor/alerts"; }}
    />
  );
}
