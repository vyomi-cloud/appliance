/* Create database — the console's numbered-step form. Every real setting goes into ONE
 * native databases.create body (+ an initial security-rules write); settings Vyomi doesn't
 * model are declared gaps, not controls. */
import { useState } from "react";
import {
  Box, Button, Checkbox, Divider, FormControl, FormControlLabel, IconButton, InputLabel,
  MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

const location_ = window.location;

function Step({ n, title, children }) {
  return (
    <Box component="section" aria-label={title} sx={{ display: "grid", gridTemplateColumns: "32px 1fr", columnGap: 2, py: 2.5 }}>
      <Box sx={{ width: 28, height: 28, borderRadius: "50%", bgcolor: "primary.main", color: "primary.contrastText", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 500 }}>{n}</Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h3" component="h2" sx={{ mb: 2, lineHeight: "28px" }}>{title}</Typography>
        <Stack spacing={2.5}>{children}</Stack>
      </Box>
    </Box>
  );
}

const OPEN_RULES = `rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if request.time < timestamp.date(2027, 1, 1);
    }
  }
}`;

export default function CreateDatabase() {
  const notify = useNotify();
  const [id, setId] = useState("(default)");
  const [touched, setTouched] = useState(false);
  const [edition, setEdition] = useState("STANDARD");
  const [mode, setMode] = useState("native");
  const [locType, setLocType] = useState("region");
  const [location, setLocation] = useState(api.DB_LOCATIONS[2][0]);
  const [showDr, setShowDr] = useState(false);
  const [pitr, setPitr] = useState(false);
  const [deleteProtection, setDeleteProtection] = useState(false);
  const [showEnc, setShowEnc] = useState(false);
  const [rules, setRules] = useState("restrictive");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const idErr = touched ? api.validDatabaseId(id) : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validDatabaseId(id)) return;
    setBusy(true); setError(null);
    try {
      await api.createDatabase(id, {
        locationId: location,
        type: mode === "datastore" ? "DATASTORE_MODE" : "FIRESTORE_NATIVE",
        databaseEdition: edition,
        pointInTimeRecoveryEnablement: pitr ? "POINT_IN_TIME_RECOVERY_ENABLED" : "POINT_IN_TIME_RECOVERY_DISABLED",
        deleteProtectionState: deleteProtection ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED",
      });
      await api.updateSecurityRules(id, rules === "open" ? OPEN_RULES : api.DEFAULT_RULES);
      notify.success(`Created database "${id}"`);
      location_.hash = hashHref("firestore", "databases", id, "studio").slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create database" back={<IconButton aria-label="Back" href="#/firestore/databases"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create database" />

      <Step n={1} title="Name your database">
        <TextField label="Database ID" required value={id} onChange={(ev) => setId(ev.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!idErr} inputProps={{ "aria-label": "Database ID" }} sx={{ maxWidth: 420 }}
          helperText={idErr || "Permanent choice. Use (default) for the default database."} />
      </Step>
      <Divider />

      <Step n={2} title="Select your edition">
        <RadioGroup value={edition} onChange={(ev) => setEdition(ev.target.value)} aria-label="Edition">
          <FormControlLabel value="ENTERPRISE" control={<Radio size="small" />} label={<><b>Enterprise Edition</b> — Native mode plus MongoDB compatibility</>} />
          <FormControlLabel value="STANDARD" control={<Radio size="small" />} label={<><b>Standard Edition</b> — Native mode or Datastore mode</>} />
        </RadioGroup>
      </Step>
      <Divider />

      <Step n={3} title="Modes">
        <RadioGroup value={mode} onChange={(ev) => setMode(ev.target.value)} aria-label="Mode">
          <FormControlLabel value="native" control={<Radio size="small" />} label="Firestore in Native mode" />
          <FormControlLabel value="mongo" control={<Radio size="small" />} label="Firestore with MongoDB compatibility" />
        </RadioGroup>
        {mode === "mongo" && <NotSimulated compact feature="MongoDB compatibility wire protocol" note="Vyomi creates the database in Native mode; the Firestore MongoDB-compatible wire protocol isn't simulated." />}
      </Step>
      <Divider />

      <Step n={4} title="Location">
        <RadioGroup value={locType} onChange={(ev) => setLocType(ev.target.value)} aria-label="Location type">
          <FormControlLabel value="region" control={<Radio size="small" />} label={<><b>Region</b> — Lowest latency within a single region</>} />
          <FormControlLabel value="multi-region" control={<Radio size="small" />} label={<><b>Multi-region</b> — Highest availability across the largest area</>} />
        </RadioGroup>
        <FormControl sx={{ maxWidth: 420 }}>
          <InputLabel id="loc-label">Region</InputLabel>
          <Select labelId="loc-label" label="Region" value={location} onChange={(ev) => setLocation(ev.target.value)} inputProps={{ "aria-label": "Region" }}>
            {api.DB_LOCATIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <Box><Button size="small" onClick={() => setShowDr((v) => !v)}>{showDr ? "Hide" : "Show"} disaster recovery settings</Button></Box>
        {showDr && (
          <Stack spacing={1} sx={{ pl: 1 }}>
            <FormControlLabel control={<Checkbox size="small" checked={pitr} onChange={(ev) => setPitr(ev.target.checked)} />} label="Enable point-in-time recovery" />
            <FormControlLabel control={<Checkbox size="small" checked={deleteProtection} onChange={(ev) => setDeleteProtection(ev.target.checked)} />} label="Enable delete protection" />
          </Stack>
        )}
        <Box><Button size="small" onClick={() => setShowEnc((v) => !v)}>{showEnc ? "Hide" : "Show"} encryption options</Button></Box>
        {showEnc && <NotSimulated compact feature="Customer-managed encryption keys (CMEK)" note="Vyomi always uses Google-managed encryption; there is no customer-key picker." />}
      </Step>
      <Divider />

      <Step n={5} title="Security rules">
        <RadioGroup value={rules} onChange={(ev) => setRules(ev.target.value)} aria-label="Security rules">
          <FormControlLabel value="restrictive" control={<Radio size="small" />} label={<><b>Restrictive</b> — Deny all client reads and writes</>} />
          <FormControlLabel value="open" control={<Radio size="small" />} label={<><b>Open</b> — Allow all client reads and writes for 30 days</>} />
        </RadioGroup>
        <NotSimulated compact feature="Security rules enforcement" note="Vyomi stores the chosen rules and shows them on the Security rules page, but never evaluates them against a request." />
      </Step>
      <Divider />

      <Step n={6} title="Pricing summary (Free-tier Eligible)">
        <Typography variant="body2" color="text.secondary">
          New databases include a free quota of storage, reads, writes and deletes each day. Usage beyond the free tier is not metered in Vyomi.
        </Typography>
      </Step>
      <Divider />

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create Database"}</Button>
        <Button href="#/firestore/databases">Cancel</Button>
      </Stack>
    </Box>
  );
}
