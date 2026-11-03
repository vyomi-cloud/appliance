/* Connect an identity provider to a workload / workforce identity pool: OIDC, SAML or AWS, plus the attribute
 * mapping and attribute condition. One native provider body; the backend (core/gcp_wif_core.py) validates the
 * issuer, JWKS, mapping expressions and CEL condition exactly like the real service. */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, Radio, RadioGroup, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ProviderDialog({ poolName, onClose, onCreated }) {
  const workforce = poolName.includes("workforcePools");
  const [type, setType] = useState("oidc");
  const [id, setId] = useState("");
  const [issuer, setIssuer] = useState("");
  const [clientId, setClientId] = useState("");
  const [audiences, setAudiences] = useState("");
  const [jwks, setJwks] = useState("");
  const [awsAccount, setAwsAccount] = useState("");
  const [saml, setSaml] = useState("");
  const [mapping, setMapping] = useState([{ k: "google.subject", v: type === "saml" ? "assertion.subject" : "assertion.sub" }]);
  const [condition, setCondition] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const idOk = /^[a-z][a-z0-9-]{2,30}[a-z0-9]$/.test(id) && !id.startsWith("gcp-");
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const body = { displayName: id, attributeMapping: Object.fromEntries(mapping.filter((m) => m.k && m.v).map((m) => [m.k, m.v])) };
      if (condition.trim()) body.attributeCondition = condition.trim();
      if (type === "oidc") {
        body.oidc = { issuerUri: issuer.trim() };
        if (workforce && clientId.trim()) body.oidc.clientId = clientId.trim();
        if (audiences.trim()) body.oidc.allowedAudiences = audiences.split(",").map((a) => a.trim()).filter(Boolean);
        if (jwks.trim()) body.oidc.jwksJson = jwks.trim();
      } else if (type === "aws") body.aws = { accountId: awsAccount.trim() };
      else body.saml = { idpMetadataXml: saml };
      await api.createProvider(poolName, id, body);
      onCreated(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="md" fullWidth aria-label="Add provider">
      <DialogTitle>Add a provider to {poolName.split("/").pop()}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to add provider" />
          <RadioGroup row value={type} onChange={(e) => setType(e.target.value)} aria-label="Provider type">
            <FormControlLabel value="oidc" control={<Radio size="small" />} label="OpenID Connect (OIDC)" />
            <FormControlLabel value="saml" control={<Radio size="small" />} label="SAML" />
            {!workforce && <FormControlLabel value="aws" control={<Radio size="small" />} label="Amazon Web Services (AWS)" />}
          </RadioGroup>
          <TextField label="Provider ID" value={id} onChange={(e) => setId(e.target.value.trim())} error={!!id && !idOk} helperText="4-32 characters: lowercase letters, digits, hyphens" inputProps={{ "aria-label": "Provider ID" }} sx={{ maxWidth: 380 }} />
          {type === "oidc" && (<>
            <TextField label="Issuer (URL)" value={issuer} onChange={(e) => setIssuer(e.target.value)} placeholder="https://token.actions.githubusercontent.com" inputProps={{ "aria-label": "Issuer URL" }} />
            {workforce && <TextField label="Client ID" value={clientId} onChange={(e) => setClientId(e.target.value)} />}
            <TextField label="Allowed audiences (optional, comma-separated)" value={audiences} onChange={(e) => setAudiences(e.target.value)} helperText="Defaults to the provider's full resource name." />
            <TextField label="JWKS JSON (optional)" value={jwks} onChange={(e) => setJwks(e.target.value)} multiline minRows={2}
              helperText="Vyomi has no network egress, so it cannot fetch the issuer's JWKS URL: paste the key set to let it verify RS256 subject tokens." inputProps={{ "aria-label": "JWKS JSON" }} />
          </>)}
          {type === "aws" && <TextField label="AWS account ID" value={awsAccount} onChange={(e) => setAwsAccount(e.target.value)} inputProps={{ "aria-label": "AWS account ID" }} sx={{ maxWidth: 280 }} />}
          {type === "saml" && <TextField label="SAML IdP metadata XML" value={saml} onChange={(e) => setSaml(e.target.value)} multiline minRows={3} inputProps={{ "aria-label": "SAML metadata" }} />}
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Attribute mapping</Typography>
            <Stack spacing={1}>
              {mapping.map((m, i) => (
                <Stack key={i} direction="row" spacing={1} alignItems="center">
                  <TextField size="small" label="Google attribute" value={m.k} disabled={i === 0} onChange={(e) => setMapping(mapping.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} sx={{ width: 220 }} inputProps={{ "aria-label": `Mapping ${i + 1} key` }} />
                  <TextField size="small" label="OIDC / SAML assertion" value={m.v} onChange={(e) => setMapping(mapping.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} sx={{ flex: 1 }} inputProps={{ "aria-label": `Mapping ${i + 1} expression` }} />
                  {i > 0 && <IconButton size="small" aria-label={`Delete mapping ${i + 1}`} onClick={() => setMapping(mapping.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>}
                </Stack>
              ))}
              <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setMapping([...mapping, { k: "attribute.", v: "assertion." }])}>Add mapping</Button></Box>
            </Stack>
          </Box>
          <TextField label="Attribute conditions (CEL, optional)" value={condition} onChange={(e) => setCondition(e.target.value)} placeholder={`assertion.repository == "acme/app"`}
            helperText="Supports ==, !=, in [..], startsWith/endsWith/contains, &&, ||, !" inputProps={{ "aria-label": "Attribute condition" }} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!idOk || busy} onClick={save}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}
