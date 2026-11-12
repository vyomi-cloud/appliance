import { useEffect, useState } from "react";
import { Input, Select } from "@fluentui/react-components";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { listResourceGroups, LOCATIONS } from "../../kit/arm.js";
import { putDataCollectionEndpoint } from "./api.js";

export default function CreateDataCollectionEndpoint() {
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [name, setName] = useState("");
  const [region, setRegion] = useState("eastus");

  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);

  const basics = (
    <FormSection title="Endpoint details">
      <FormRow label="Resource group" required>
        <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
          <option value="cloudlearn-rg">cloudlearn-rg</option>
          {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Endpoint name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Endpoint name" /></FormRow>
      <FormRow label="Region" required>
        <Select value={region} onChange={(_, d) => setRegion(d.value)} aria-label="Region">{LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</Select>
      </FormRow>
    </FormSection>
  );

  return (
    <CreateWizard title="Create data collection endpoint" closeHref="#/monitor/datacollectionendpoints" glyph={<Glyph id="monitor" size={32} />}
      tabs={[{ id: "basics", label: "Basics", content: basics, validate: () => (name ? [] : ["Endpoint name is required."]) }]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Name"><span>{name}</span></FormRow>
          <FormRow label="Resource group"><span>{rg}</span></FormRow>
          <FormRow label="Region"><span>{LOCATIONS.find(([id]) => id === region)?.[1] || region}</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => { await putDataCollectionEndpoint(rg, name, { location: region, properties: {} }); location.hash = "#/monitor/datacollectionendpoints"; }}
    />
  );
}
