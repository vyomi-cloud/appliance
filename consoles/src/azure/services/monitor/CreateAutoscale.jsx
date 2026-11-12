import { useEffect, useState } from "react";
import { Input, Select } from "@fluentui/react-components";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { listResourceGroups } from "../../kit/arm.js";
import { listAllResources, putAutoscaleSetting } from "./api.js";

export default function CreateAutoscale() {
  const [resources, setResources] = useState([]);
  const [target, setTarget] = useState("");
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [name, setName] = useState("");
  const [min, setMin] = useState("1");
  const [max, setMax] = useState("5");
  const [def, setDef] = useState("1");

  useEffect(() => {
    listAllResources().then((r) => { setResources(r); setTarget(r[0]?.id || ""); }).catch(() => setResources([]));
    listResourceGroups().then(setRgs).catch(() => setRgs([]));
  }, []);

  const resource = resources.find((r) => r.id === target);

  const basics = (
    <FormSection title="Scale mode and instance limits">
      <FormRow label="Target resource" required>
        {resources.length ? (
          <Select value={target} onChange={(_, d) => setTarget(d.value)} aria-label="Target resource">
            {resources.map((r) => <option key={r.id} value={r.id}>{r.name} — {r.typeLabel}</option>)}
          </Select>
        ) : <p>No resources yet to scale.</p>}
      </FormRow>
      <FormRow label="Resource group" required>
        <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
          <option value="cloudlearn-rg">cloudlearn-rg</option>
          {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></FormRow>
      <FormRow label="Minimum" required><Input type="number" min="0" value={min} onChange={(_, d) => setMin(d.value)} aria-label="Minimum" /></FormRow>
      <FormRow label="Maximum" required><Input type="number" min="0" value={max} onChange={(_, d) => setMax(d.value)} aria-label="Maximum" /></FormRow>
      <FormRow label="Default" required><Input type="number" min="0" value={def} onChange={(_, d) => setDef(d.value)} aria-label="Default" /></FormRow>
    </FormSection>
  );

  const body = () => ({
    location: resource?.location || "eastus",
    properties: {
      targetResourceUri: target, name,
      profiles: [{ name: "default", capacity: { minimum: min, maximum: max, default: def }, rules: [] }],
    },
  });

  return (
    <CreateWizard title="Add an autoscale setting" closeHref="#/monitor/autoscale" glyph={<Glyph id="monitor" size={32} />}
      tabs={[{ id: "basics", label: "Scale settings", content: basics, validate: () => [
        ...(name ? [] : ["Name is required."]),
        ...(Number(min) <= Number(def) && Number(def) <= Number(max) ? [] : ["Capacity must satisfy minimum ≤ default ≤ maximum."]),
      ] }]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Name"><span>{name}</span></FormRow>
          <FormRow label="Target resource"><span>{resource?.name || "--"}</span></FormRow>
          <FormRow label="Instances"><span>{min} - {max} (default {def})</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => { await putAutoscaleSetting(rg, name, body()); location.hash = "#/monitor/autoscale"; }}
    />
  );
}
