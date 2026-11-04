import { useEffect, useState } from "react";
import { Input, Select } from "@fluentui/react-components";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { listResourceGroups } from "../../kit/arm.js";
import { putPrivateLinkScope } from "./api.js";

const ACCESS_MODES = ["Open", "PrivateOnly"];

export default function CreatePrivateLinkScope() {
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [name, setName] = useState("");
  const [queryMode, setQueryMode] = useState("Open");
  const [ingestMode, setIngestMode] = useState("Open");

  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);

  const basics = (
    <FormSection title="Instance details">
      <FormRow label="Resource group" required>
        <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
          <option value="cloudlearn-rg">cloudlearn-rg</option>
          {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></FormRow>
      <FormRow label="Region"><span>Global</span></FormRow>
    </FormSection>
  );

  const access = (
    <FormSection title="Access mode settings">
      <FormRow label="Query access mode">
        <Select value={queryMode} onChange={(_, d) => setQueryMode(d.value)} aria-label="Query access mode">
          {ACCESS_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Ingestion access mode">
        <Select value={ingestMode} onChange={(_, d) => setIngestMode(d.value)} aria-label="Ingestion access mode">
          {ACCESS_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </Select>
      </FormRow>
    </FormSection>
  );

  return (
    <CreateWizard title="Create Azure Monitor Private Link Scope" closeHref="#/monitor/privatelinkscopes" glyph={<Glyph id="monitor" size={32} />}
      tabs={[
        { id: "basics", label: "Basics", content: basics, validate: () => (name ? [] : ["Name is required."]) },
        { id: "access", label: "Access mode", content: access, validate: () => [] },
      ]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Name"><span>{name}</span></FormRow>
          <FormRow label="Resource group"><span>{rg}</span></FormRow>
          <FormRow label="Query access mode"><span>{queryMode}</span></FormRow>
          <FormRow label="Ingestion access mode"><span>{ingestMode}</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => {
        await putPrivateLinkScope(rg, name, {
          location: "global",
          properties: { accessModeSettings: { queryAccessMode: queryMode, ingestionAccessMode: ingestMode } },
        });
        location.hash = "#/monitor/privatelinkscopes";
      }}
    />
  );
}
