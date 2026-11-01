/* Cloud SQL Studio — an in-console SQL editor. NOT part of the real Admin REST API (the
 * real Studio isn't either — it runs on a separate Google-internal channel); this page
 * is backed by a small data-plane RPC this core adds next to the real control plane
 * (api.runQuery -> POST .../instances/{i}/query), the same way core/azure_sql_core.py adds
 * its own `/query` path beside Azure SQL's real ARM control plane. Queries run for REAL
 * against the instance's real engine (sqlite3 in Nano, a real Postgres/MySQL in Pro/Max —
 * the SAME engine instances.export/import already drive).
 *
 * "Require SSL/TLS" (Connections > Security) is enforced here: when the instance requires
 * an encrypted session or a trusted client certificate, this editor sends that proof with
 * every query, and the backend genuinely rejects the query without it — see
 * core/capabilities/gcp/sql.json: gcp.sql.connections-security / gcp.sql.insights. */
import { useEffect, useState } from "react";
import { Alert, Box, Button, MenuItem, Stack, TextField, Typography } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

const SAMPLE = "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)";

export default function CloudSqlStudio({ params }) {
  const name = params.name;
  const inst = useAsync(() => api.getInstance(name), [name]);
  const tables = useAsync(() => api.listTables(name), [name]);
  const certs = useAsync(() => api.listSslCerts(name), [name]);
  const notify = useNotify();
  const [sql, setSql] = useState("SELECT 1");
  const [certFp, setCertFp] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const sslMode = inst.data?.settings?.ipConfiguration?.sslMode || "ALLOW_UNENCRYPTED_AND_ENCRYPTED";
  const needsCert = sslMode === "TRUSTED_CLIENT_CERTIFICATE_REQUIRED";

  useEffect(() => {
    if (needsCert && !certFp && certs.data?.length) setCertFp(certs.data[0].sha1Fingerprint);
  }, [needsCert, certs.data, certFp]);

  const run = async () => {
    setRunning(true);
    try {
      const r = await api.runQuery(name, sql, {
        ssl: sslMode !== "ALLOW_UNENCRYPTED_AND_ENCRYPTED",
        clientCertSha1Fingerprint: certFp || undefined,
      });
      setResult(r);
      if (r.ok) { notify.success(`${r.rowCount} row(s) in ${r.durationMs}ms`); tables.reload(); }
    } catch (e) { setResult(null); notify.error(e); }
    finally { setRunning(false); }
  };

  return (
    <>
      <InstanceNav name={name} active="studio" />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>Cloud SQL Studio</Typography>
      <Stack spacing={2.5}>
        <CapabilityContainer id="gcp.sql.insights" title="Editor">
          <Stack spacing={2}>
            {needsCert && !certFp && (
              <Alert severity="warning">
                This instance requires a trusted client certificate. Create one under Connections &gt; Security before running queries.
              </Alert>
            )}
            {needsCert && certs.data?.length > 0 && (
              <TextField select size="small" label="Client certificate" value={certFp}
                onChange={(e) => setCertFp(e.target.value)} sx={{ maxWidth: 420 }}>
                {certs.data.map((c) => <MenuItem key={c.sha1Fingerprint} value={c.sha1Fingerprint}>{c.commonName}</MenuItem>)}
              </TextField>
            )}
            <TextField multiline minRows={6} fullWidth value={sql} onChange={(e) => setSql(e.target.value)}
              inputProps={{ "aria-label": "SQL editor", style: { fontFamily: "monospace", fontSize: 13 } }} />
            <Stack direction="row" spacing={1}>
              <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={running || (needsCert && !certFp)} onClick={run}>Run</Button>
              <Button onClick={() => setSql(SAMPLE)}>Sample statement</Button>
            </Stack>
            {result && (result.ok ? (
              <Box sx={{ overflowX: "auto" }}>
                {result.columns.length > 0 ? (
                  <Box component="table" sx={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                    <Box component="thead"><Box component="tr">
                      {result.columns.map((c) => <Box key={c} component="th" sx={{ textAlign: "left", borderBottom: 1, borderColor: "divider", p: 0.75 }}>{c}</Box>)}
                    </Box></Box>
                    <Box component="tbody">
                      {result.rows.map((r, i) => (
                        <Box component="tr" key={i}>
                          {r.map((v, j) => <Box key={j} component="td" sx={{ p: 0.75, borderBottom: 1, borderColor: "divider" }}>{v === null ? "NULL" : String(v)}</Box>)}
                        </Box>
                      ))}
                    </Box>
                  </Box>
                ) : <Typography variant="body2" color="text.secondary">{result.rowCount} row(s) affected.</Typography>}
              </Box>
            ) : <Alert severity="error">{result.error}</Alert>)}
          </Stack>
        </CapabilityContainer>
        <Section title="Tables">
          {tables.data?.length ? (
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
              {tables.data.map((t) => <Button key={t} size="small" onClick={() => setSql(`SELECT * FROM ${t} LIMIT 50`)}>{t}</Button>)}
            </Stack>
          ) : <Typography variant="body2" color="text.secondary">No tables yet — run a CREATE TABLE statement.</Typography>}
        </Section>
      </Stack>
    </>
  );
}
