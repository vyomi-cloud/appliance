/* Replicas — honest gap: Vyomi has no replication engine (see
 * core/capabilities/gcp/sql.json: gcp.sql.replicas is "not_simulated"). */
import { Stack, Typography } from "@mui/material";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";

export default function Replicas({ params }) {
  return (
    <>
      <InstanceNav name={params.name} active="replicas" />
      <Stack spacing={1.5}>
        <Typography variant="h2" component="h2" sx={{ fontSize: 20 }}>Replicas</Typography>
        <CapabilityContainer id="gcp.sql.replicas" title="Read replicas" />
      </Stack>
    </>
  );
}
