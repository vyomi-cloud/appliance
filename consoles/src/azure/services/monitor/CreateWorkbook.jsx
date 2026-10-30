import { useEffect, useState } from "react";
import { Input, Select, Textarea } from "@fluentui/react-components";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { listResourceGroups } from "../../kit/arm.js";
import { putWorkbook } from "./api.js";

const TEMPLATES = { Empty: "{}", Dashboard: JSON.stringify({ version: "Notebook/1.0", items: [{ type: 1, content: { json: "# Dashboard" } }] }) };

export default function CreateWorkbook() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState(params.get("template") === "Dashboard" ? "New dashboard" : "New workbook");
  const [category, setCategory] = useState("workbook");
  const [data, setData] = useState(TEMPLATES[params.get("template")] || TEMPLATES.Empty);

  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);

  const basics = (
    <FormSection title="Workbook details">
      <FormRow label="Resource group" required>
        <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
          <option value="cloudlearn-rg">cloudlearn-rg</option>
          {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} placeholder="GUID-like identifier" aria-label="Name" /></FormRow>
      <FormRow label="Title" required><Input value={displayName} onChange={(_, d) => setDisplayName(d.value)} aria-label="Title" /></FormRow>
      <FormRow label="Category"><Input value={category} onChange={(_, d) => setCategory(d.value)} aria-label="Category" /></FormRow>
      <FormRow label="Content (JSON)"><Textarea rows={6} value={data} onChange={(_, d) => setData(d.value)} aria-label="Content (JSON)" /></FormRow>
    </FormSection>
  );

  return (
    <CreateWizard title="New workbook" closeHref="#/monitor/workbooks" glyph={<Glyph id="monitor" size={32} />}
      tabs={[{ id: "basics", label: "Basics", content: basics, validate: () => [
        ...(name ? [] : ["Name is required."]), ...(displayName ? [] : ["Title is required."]),
      ] }]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Title"><span>{displayName}</span></FormRow>
          <FormRow label="Resource group"><span>{rg}</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => {
        await putWorkbook(rg, name, { location: "eastus", properties: { displayName, category, serializedData: data } });
        location.hash = "#/monitor/workbooks";
      }}
    />
  );
}
