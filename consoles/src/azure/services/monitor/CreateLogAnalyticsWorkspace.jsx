import { useEffect, useState } from "react";
import { Input, Select } from "@fluentui/react-components";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { listResourceGroups, LOCATIONS } from "../../kit/arm.js";
import { putWorkspace, WORKSPACE_SKUS } from "./api.js";

export default function CreateLogAnalyticsWorkspace() {
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [name, setName] = useState("");
  const [region, setRegion] = useState("eastus");
  const [sku, setSku] = useState("PerGB2018");

  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);

  const basics = (
    <FormSection title="Project details">
      <FormRow label="Resource group" required>
        <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
          <option value="cloudlearn-rg">cloudlearn-rg</option>
          {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></FormRow>
      <FormRow label="Region" required>
        <Select value={region} onChange={(_, d) => setRegion(d.value)} aria-label="Region">{LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</Select>
      </FormRow>
      <FormRow label="Pricing tier">
        <Select value={sku} onChange={(_, d) => setSku(d.value)} aria-label="Pricing tier">{WORKSPACE_SKUS.map((s) => <option key={s}>{s}</option>)}</Select>
      </FormRow>
    </FormSection>
  );

  return (
    <CreateWizard title="Create Log Analytics workspace" closeHref="#/monitor/loganalyticsworkspaces" glyph={<Glyph id="monitor" size={32} />}
      tabs={[{ id: "basics", label: "Basics", content: basics, validate: () => (name ? [] : ["Name is required."]) }]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Name"><span>{name}</span></FormRow>
          <FormRow label="Resource group"><span>{rg}</span></FormRow>
          <FormRow label="Region"><span>{region}</span></FormRow>
          <FormRow label="Pricing tier"><span>{sku}</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => { await putWorkspace(rg, name, { location: region, properties: { sku: { name: sku } } }); location.hash = "#/monitor/loganalyticsworkspaces"; }}
    />
  );
}
