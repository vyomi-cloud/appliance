import { useEffect, useState } from "react";
import { Input, Select } from "@fluentui/react-components";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import { listResourceGroups } from "../../kit/arm.js";
import { putActionGroup } from "./api.js";

export default function CreateActionGroup() {
  const [name, setName] = useState("");
  const [shortName, setShortName] = useState("");
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("cloudlearn-rg");
  const [email, setEmail] = useState("");

  useEffect(() => { listResourceGroups().then(setRgs).catch(() => setRgs([])); }, []);

  const basics = (
    <FormSection title="Project details">
      <FormRow label="Resource group" required>
        <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Resource group">
          <option value="cloudlearn-rg">cloudlearn-rg</option>
          {rgs.filter((r) => r.name !== "cloudlearn-rg").map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Action group name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Action group name" /></FormRow>
      <FormRow label="Display name" required info="Shown in notifications sent by this group (max 12 characters).">
        <Input value={shortName} onChange={(_, d) => setShortName(d.value.slice(0, 12))} aria-label="Display name" />
      </FormRow>
      <FormRow label="Email"><Input type="email" value={email} onChange={(_, d) => setEmail(d.value)} placeholder="(optional)" aria-label="Email" /></FormRow>
    </FormSection>
  );

  const body = () => ({
    location: "Global",
    properties: { groupShortName: shortName, enabled: true, ...(email ? { emailReceivers: [{ name: "email-1", emailAddress: email }] } : {}) },
  });

  return (
    <CreateWizard title="Create action group" closeHref="#/monitor/actiongroups" glyph={<Glyph id="monitor" size={32} />}
      tabs={[{ id: "basics", label: "Basics", content: basics, validate: () => [
        ...(name ? [] : ["Action group name is required."]), ...(shortName ? [] : ["Display name is required."]),
      ] }]}
      review={() => (
        <FormSection title="Summary">
          <FormRow label="Name"><span>{name}</span></FormRow>
          <FormRow label="Display name"><span>{shortName}</span></FormRow>
          <FormRow label="Resource group"><span>{rg}</span></FormRow>
          <FormRow label="Email"><span>{email || "(none)"}</span></FormRow>
        </FormSection>
      )}
      onCreate={async () => { await putActionGroup(rg, name, body()); location.hash = "#/monitor/actiongroups"; }}
    />
  );
}
