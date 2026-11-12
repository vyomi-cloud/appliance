/* Connectivity Test detail — reachability result + hop-by-hop trace, rerun, delete.
 * `reachabilityDetails.traces[0].steps` comes straight from core/gcp_compute_core.py's
 * _ct_steps(), itself built from the shared netsim evaluator's Verdict hops. */
import { useState } from "react";
import { Box, Button, Chip, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import ReplayIcon from "@mui/icons-material/esm/Replay.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import CheckCircleIcon from "@mui/icons-material/esm/CheckCircleOutlined.js";
import CancelIcon from "@mui/icons-material/esm/CancelOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ConnectivityTestDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const [busy, setBusy] = useState(false);
  const { data: test, error, reload } = useAsync(() => api.getConnectivityTest(name), [name]);

  const rerun = async () => {
    setBusy(true);
    try { await api.rerunConnectivityTest(name); notify.success("Connectivity test re-run"); reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  const details = test?.reachabilityDetails;
  const trace = details?.traces?.[0];
  const reachable = details?.result === "REACHABLE";

  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back" href="#/networking/connectivity-tests/list"><ArrowBackIcon /></IconButton>} actions={<>
        <Button startIcon={<ReplayIcon />} disabled={busy} onClick={rerun}>{busy ? "Running…" : "Rerun"}</Button>
        <Button color="error" startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ErrorAlert error={error} />
      {test && (
        <Stack spacing={2}>
          <Section title="Test configuration">
            <KeyValue items={[
              ["Description", test.description || "—"],
              ["Protocol", test.protocol],
              ["Source", api.endpointLabel(test.source)],
              ["Destination", api.endpointLabel(test.destination)],
              ["Destination port", test.destination?.port ?? "—"],
            ]} />
          </Section>
          <Section title="Reachability analysis" description={details ? `Last tested ${fmtDate(details.verifyTime)}` : null}>
            {details ? (
              <Stack spacing={2}>
                <Chip icon={reachable ? <CheckCircleIcon /> : <CancelIcon />} color={reachable ? "success" : "error"}
                  label={reachable ? "Reachable" : "Unreachable"} sx={{ fontWeight: 500, alignSelf: "flex-start" }} />
                {trace && (
                  <Stack spacing={1}>
                    <Typography variant="subtitle2">Trace</Typography>
                    {trace.steps.map((s, i) => (
                      <Stack key={i} direction="row" spacing={1.5} alignItems="flex-start">
                        <Chip size="small" color={s.causesDrop ? "error" : (s.state === "DELIVER" ? "success" : "default")}
                          label={api.ctStepLabel(s)} sx={{ minWidth: 150 }} />
                        <Typography variant="body2" sx={{ pt: 0.25 }}>{s.description}{s.drop ? ` (${s.drop.cause})` : ""}</Typography>
                      </Stack>
                    ))}
                  </Stack>
                )}
              </Stack>
            ) : <Typography variant="body2" color="text.secondary">No reachability data yet.</Typography>}
          </Section>
        </Stack>
      )}

      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete connectivity test?" confirmText={name}
        onConfirm={async () => {
          await api.deleteConnectivityTest(name);
          notify.success(`Deleted connectivity test "${name}"`);
          window.location.hash = "#/networking/connectivity-tests/list";
        }}
      >
        <Typography variant="body2">Connectivity test <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
