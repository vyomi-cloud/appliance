/* Edit password policy — real UpdateAccountPasswordPolicy / DeleteAccountPasswordPolicy. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Checkbox from "@cloudscape-design/components/checkbox";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function EditPasswordPolicy() {
  const notify = useNotify();
  const p = useAsync(() => api.getAccountPasswordPolicy(), []);
  const [mode, setMode] = useState("IAM default");
  const [minLength, setMinLength] = useState(8);
  const [reqUpper, setReqUpper] = useState(false);
  const [reqLower, setReqLower] = useState(false);
  const [reqNumber, setReqNumber] = useState(false);
  const [reqSymbol, setReqSymbol] = useState(false);
  const [expire, setExpire] = useState(false);
  const [maxAge, setMaxAge] = useState(90);
  const [hardExpiry, setHardExpiry] = useState(false);
  const [allowChange, setAllowChange] = useState(true);
  const [reusePrevention, setReusePrevention] = useState(false);
  const [reuseCount, setReuseCount] = useState(5);
  const [busy, setBusy] = useState(false);

  if (p.loading) return <Box padding="l">Loading…</Box>;

  const submit = async () => {
    setBusy(true);
    try {
      if (mode === "IAM default") { await api.deleteAccountPasswordPolicy(); }
      else {
        await api.updateAccountPasswordPolicy({
          MinimumPasswordLength: minLength,
          RequireUppercaseCharacters: String(reqUpper), RequireLowercaseCharacters: String(reqLower),
          RequireNumbers: String(reqNumber), RequireSymbols: String(reqSymbol),
          ExpirePasswords: String(expire), MaxPasswordAge: maxAge, HardExpiry: String(hardExpiry),
          AllowUsersToChangePassword: String(allowChange),
          PasswordReusePrevention: reusePrevention ? reuseCount : 0,
        });
      }
      notify.success(`Password policy saved.${saveNotice("iam.account-settings.password-policy")}`);
      navigate("iam", "account-settings");
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <Box padding={{ top: "l", bottom: "xxl" }}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Password policy</Header>}>
          <SpaceBetween size="m">
            <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)} items={[{ value: "IAM default", label: "IAM default" }, { value: "Custom", label: "Custom" }]} />
            {mode === "Custom" && (
              <SpaceBetween size="m">
                <FormField label="Password minimum length"><Input type="number" value={String(minLength)} onChange={({ detail }) => setMinLength(Number(detail.value))} ariaLabel="Password minimum length" /></FormField>
                <FormField label="Password strength">
                  <SpaceBetween size="xs">
                    <Checkbox checked={reqUpper} onChange={({ detail }) => setReqUpper(detail.checked)}>Require at least one uppercase letter</Checkbox>
                    <Checkbox checked={reqLower} onChange={({ detail }) => setReqLower(detail.checked)}>Require at least one lowercase letter</Checkbox>
                    <Checkbox checked={reqNumber} onChange={({ detail }) => setReqNumber(detail.checked)}>Require at least one number</Checkbox>
                    <Checkbox checked={reqSymbol} onChange={({ detail }) => setReqSymbol(detail.checked)}>Require at least one non-alphanumeric character</Checkbox>
                  </SpaceBetween>
                </FormField>
                <FormField label="Other requirements">
                  <SpaceBetween size="xs">
                    <Checkbox checked={expire} onChange={({ detail }) => setExpire(detail.checked)}>Turn on password expiration</Checkbox>
                    {expire && <FormField label="Password expiration period (in days)"><Input type="number" value={String(maxAge)} onChange={({ detail }) => setMaxAge(Number(detail.value))} ariaLabel="Password expiration period (in days)" /></FormField>}
                    <Checkbox checked={hardExpiry} onChange={({ detail }) => setHardExpiry(detail.checked)}>Password expiration requires administrator reset</Checkbox>
                    <Checkbox checked={allowChange} onChange={({ detail }) => setAllowChange(detail.checked)}>Allow users to change their own password</Checkbox>
                    <Checkbox checked={reusePrevention} onChange={({ detail }) => setReusePrevention(detail.checked)}>Prevent password reuse</Checkbox>
                    {reusePrevention && <FormField label="Number of passwords to remember"><Input type="number" value={String(reuseCount)} onChange={({ detail }) => setReuseCount(Number(detail.value))} ariaLabel="Number of passwords to remember" /></FormField>}
                  </SpaceBetween>
                </FormField>
              </SpaceBetween>
            )}
          </SpaceBetween>
        </Container>
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => navigate("iam", "account-settings")}>Cancel</Button>
            <Button variant="primary" loading={busy} onClick={submit}>Save changes</Button>
          </SpaceBetween>
        </Box>
      </SpaceBetween>
    </Box>
  );
}
