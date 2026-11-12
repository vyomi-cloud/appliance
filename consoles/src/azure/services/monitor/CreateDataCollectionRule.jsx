import { useEffect, useState } from "react";
import { Checkbox, Input, Select } from "@fluentui/react-components";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { listResourceGroups, LOCATIONS } from "../../kit/arm.js";
import { listWorkspaces, putDataCollectionRule } from "./api.js";

const STREAMS = ["Microsoft-Perf", "Microsoft-Syslog", "Microsoft-Event", "Microsoft-InsightsMetrics"];

export default function CreateDataCollectionRule() {
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [name, setName] = useState("");
  const [region, setRegion] = useState("eastus");
  const [workspaces, setWorkspaces] = useState([]);
  const [workspace, setWorkspace] = useState("");
  const [streams, setStreams] = useState(new Set([STREAMS[0]]));

  useEffect(() => {
    listResourceGroups().then(setRgs).catch(() => setRgs([]));
    listWorkspaces().then((ws) => { setWorkspaces(ws); setWorkspace(ws[0]?.id || ""); }).catch(() => setWorkspaces([]));
  }, []);

  const toggle = (s) => setStreams((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });

  const basics = (
    <FormSection title="Rule details">
      <FormRow label="Resource group" required>
        <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
          <option value="cloudlearn-rg">cloudlearn-rg</option>
          {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Rule name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Rule name" /></FormRow>
      <FormRow label="Region" required>
        <Select value={region} onChange={(_, d) => setRegion(d.value)} aria-label="Region">{LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</Select>
      </FormRow>
    </FormSection>
  );

  const resources = (
    <FormSection title="Data sources">
      {STREAMS.map((s) => <div key={s}><Checkbox label={s} checked={streams.has(s)} onChange={() => toggle(s)} /></div>)}
    </FormSection>
  );

  const destinations = (
    <FormSection title="Destinations">
      <FormRow label="Log Analytics workspace" required>
        {workspaces.length ? (
          <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
            {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </Select>
        ) : <p>No Log Analytics workspace yet. <a href="#/monitor/createloganalyticsworkspace">Create one</a></p>}
      </FormRow>
    </FormSection>
  );

  const body = () => ({
    location: region,
    properties: {
      dataSources: {}, destinations: { logAnalytics: [{ name: "destination-1", workspaceResourceId: workspace }] },
      dataFlows: [{ streams: [...streams], destinations: ["destination-1"] }],
    },
  });

  return (
    <CreateWizard title="Create a data collection rule" closeHref="#/monitor/datacollectionrules" glyph={<Glyph id="monitor" size={32} />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: () => (name ? [] : ["Rule name is required."]) },
        { id: "resources", label: "Resources", content: resources, validate: () => (streams.size ? [] : ["Select at least one data source."]) },
        { id: "destinations", label: "Destination", content: destinations, validate: () => (workspace ? [] : ["Select a Log Analytics workspace."]) },
      ]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Name"><span>{name}</span></FormRow>
          <FormRow label="Streams"><span>{[...streams].join(", ")}</span></FormRow>
          <FormRow label="Destination"><span>{workspaces.find((w) => w.id === workspace)?.name || "--"}</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => { await putDataCollectionRule(rg, name, body()); location.hash = "#/monitor/datacollectionrules"; }}
    />
  );
}
