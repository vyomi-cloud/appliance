/* Register an application — single-page form (no multi-step wizard in the real console
 * either). Creating the registration auto-creates its enterprise application (service
 * principal), exactly like the real Microsoft Graph behaviour. */
import { useState } from "react";
import { Input, Option, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph } from "../../kit/common.jsx";
import * as api from "./api.js";

const AUDIENCES = [
  ["AzureADMyOrg", "Single tenant only - Default Directory"],
  ["AzureADMultipleOrgs", "Multiple Entra ID tenants"],
  ["AzureADandPersonalMicrosoftAccount", "Any Entra ID Tenant + Personal Microsoft accounts"],
  ["PersonalMicrosoftAccount", "Personal accounts only"],
];

export default function RegisterApplication() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [audience, setAudience] = useState("AzureADMyOrg");
  const [platform, setPlatform] = useState("");
  const [redirectUri, setRedirectUri] = useState("");

  const validate = () => (name.trim() ? [] : ["Name is required."]);

  const create = async () => {
    try {
      const web = platform === "Web" && redirectUri ? { redirectUris: [redirectUri] } : undefined;
      const spa = platform === "Single-page application (SPA)" && redirectUri ? { redirectUris: [redirectUri] } : undefined;
      const app = await api.createApplication({ displayName: name, signInAudience: audience, web, spa });
      notify.success(`Registered ${name}.`, "Application registered");
      navigate("entra", "appregistrations", app.id);
    } catch (e) { notify.error(e, "Register application failed"); }
  };

  return (
    <CreateWizard title="Register an application" glyph={<Glyph id="entra" />} closeHref="#/entra/appregistrations" onCreate={create}
      tabs={[{
        id: "basics", label: "Basics", validate,
        content: (
          <>
            <FormSection title="Name">
              <FormRow label="Name" required htmlFor="app-name" info="The user-facing display name for this application">
                <Input id="app-name" value={name} onChange={(_, d) => setName(d.value)} style={{ width: 360 }} />
              </FormRow>
            </FormSection>
            <FormSection title="Supported account types">
              <FormRow label="Who can use this application or access this API?">
                <RadioGroup value={audience} onChange={(_, d) => setAudience(d.value)}>
                  {AUDIENCES.map(([v, l]) => <Radio key={v} value={v} label={l} />)}
                </RadioGroup>
              </FormRow>
            </FormSection>
            <FormSection title="Redirect URI (optional)">
              <FormRow label="Select a platform">
                <Select value={platform} onChange={(_, d) => setPlatform(d.value)} style={{ width: 280 }}>
                  <option value="">Select a platform</option>
                  <option>Web</option>
                  <option>Single-page application (SPA)</option>
                  <option>Public client/native (mobile &amp; desktop)</option>
                </Select>
              </FormRow>
              <FormRow label="Redirect URI">
                <Input value={redirectUri} onChange={(_, d) => setRedirectUri(d.value)} placeholder="e.g. https://example.com/auth" style={{ width: 360 }} />
              </FormRow>
            </FormSection>
          </>
        ),
      }]}
      review={() => (
        <FormSection title="Name">
          <FormRow label="Name">{name}</FormRow>
        </FormSection>
      )}
    />
  );
}
