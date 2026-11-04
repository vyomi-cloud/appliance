/* Connections — connection endpoint + AUTH string (real getAuthString call), and the
 * network/encryption settings the instance was created with. */
import { useState } from "react";
import { Alert, Button, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Connections({ params }) {
  const { location: loc, id } = params;
  const notify = useNotify();
  const [authString, setAuthString] = useState(null);
  const inst = useAsync(() => api.getInstance(loc, id), [loc, id]);
  const i = inst.data;

  const showAuth = async () => {
    try { setAuthString((await api.getAuthString(loc, id)).authString); }
    catch (e) { notify.error(e); }
  };

  const downloadCert = () => {
    const cert = i.serverCaCerts?.[0]?.cert || "";
    const a = document.createElement("a");
    a.href = `data:application/x-pem-file;charset=utf-8,${encodeURIComponent(cert)}`;
    a.download = `${id}-server-ca.pem`;
    a.click();
  };

  return (
    <>
      <InstanceNav location={loc} id={id} active="connections" />
      <Typography variant="h2" component="h2" sx={{ fontSize: 20, mb: 1.5 }}>Connections</Typography>
      <ErrorAlert error={inst.error} title="Failed to load instance" />
      {i && (
        <Stack spacing={2}>
          <CapabilityContainer id="gcp.memorystore.connections" title="Connect to this instance">
            <KeyValue items={[
              ["Primary endpoint", api.endpoint(i)],
              ["Read endpoint", api.readEndpoint(i)],
              ["Port", i.port],
              ["AUTH string", i.authEnabled
                ? <Stack direction="row" spacing={1} alignItems="center">
                    <Typography component="span" variant="body2">{authString || "••••••••••••••••"}</Typography>
                    <Button size="small" onClick={showAuth}>Show</Button>
                  </Stack>
                : "AUTH is not enabled on this instance"],
              ["Connect command", api.connectCommand(i)],
            ]} />
          </CapabilityContainer>
          <Section title="Network">
            <KeyValue items={[
              ["Network", api.networkName(i)],
              ["Connection mode", i.connectMode === "PRIVATE_SERVICE_ACCESS" ? "Private services access" : "Direct peering"],
              ["Reserved IP range", i.reservedIpRange],
              ["In-transit encryption", i.transitEncryptionMode === "SERVER_AUTHENTICATION" ? "Enabled" : "Disabled"],
              ["Server CA certificate", i.transitEncryptionMode === "SERVER_AUTHENTICATION"
                ? <Button size="small" onClick={downloadCert}>Download</Button>
                : <Button size="small" disabled>Download</Button>],
            ]} />
            {i.transitEncryptionMode === "SERVER_AUTHENTICATION" && (
              <Alert severity="info" sx={{ mt: 2 }}>Vyomi's server certificate is a synthetic placeholder: a client cannot actually negotiate TLS against it.</Alert>
            )}
          </Section>
        </Stack>
      )}
    </>
  );
}
