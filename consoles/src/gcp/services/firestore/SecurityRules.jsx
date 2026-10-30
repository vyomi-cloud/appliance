/* Security rules — Rules editor (stored and returned verbatim, never evaluated: see the
 * capability badge) and a Development & test tab (the rules playground isn't simulated). */
import { useState } from "react";
import { Box, Button, Stack, Tab, Tabs, TextField } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulatedContainer, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TABS = [["rules", "Rules"], ["test", "Development & test"]];

export default function SecurityRules({ params, query }) {
  const db = params.name;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "rules";
  return (
    <>
      <PageHeader title="Security rules" />
      <Tabs value={tab} onChange={(_, t) => { location.hash = `#/firestore/databases/${encodeURIComponent(db)}/rules${t === "rules" ? "" : "?tab=" + t}`; }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Security rules tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "rules" ? <RulesEditor db={db} /> : <NotSimulatedContainer title="Development & test" feature="Rules Playground" note="Simulating a request against the rules requires evaluating them, which Vyomi never does." />}
    </>
  );
}

function RulesEditor({ db }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getSecurityRules(db), [db]);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const value = draft ?? data ?? "";

  const publish = async () => {
    setBusy(true);
    try {
      await api.updateSecurityRules(db, value);
      notify.success(`Rules published.${saveNotice("gcp.firestore.security-rules")}`);
      reload();
    } catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };

  return (
    <CapabilityContainer id="gcp.firestore.security-rules" title="Rules" actions={<Button variant="contained" disabled={busy || loading} onClick={publish}>{busy ? "Publishing…" : "Publish"}</Button>}>
      <ErrorAlert error={error} title="Failed to load rules" />
      <Box sx={{ mt: 1 }}>
        <TextField
          multiline fullWidth minRows={14} value={value} onChange={(e) => setDraft(e.target.value)}
          inputProps={{ "aria-label": "Rules editor", style: { fontFamily: "monospace", fontSize: 13 } }}
          placeholder={api.DEFAULT_RULES}
        />
      </Box>
      <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
        <Button size="small" onClick={() => setDraft(api.DEFAULT_RULES)}>Reset to restrictive default</Button>
      </Stack>
    </CapabilityContainer>
  );
}
