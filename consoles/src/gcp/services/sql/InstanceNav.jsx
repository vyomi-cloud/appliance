/* Shared instance-scoped header + sub-navigation strip. The real console swaps the left
 * nav for instance-scoped items (Overview, Connections, Users, …) once an instance is open;
 * Vyomi renders the same set of destinations as a link strip under the instance name so
 * each one is still its own route (and its own ui-spec page). */
import { Box, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { Link, hashHref } from "../../link.jsx";

export const SECTIONS = [
  ["overview", "Overview"], ["system-insights", "System insights"], ["query-insights", "Query insights"],
  ["studio", "Cloud SQL Studio"], ["connections", "Connections"], ["users", "Users"], ["databases", "Databases"],
  ["backups", "Backups"], ["replicas", "Replicas"], ["operations", "Operations"],
];

export const instanceHref = (name, section = "overview") => hashHref("sql", "instances", name, section);

export default function InstanceNav({ name, active, actions }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ minHeight: 48, flexWrap: "wrap", rowGap: 1 }}>
        <IconButton aria-label="Back to instances" href="#/sql"><ArrowBackIcon /></IconButton>
        <Typography variant="h1" component="h1">{name}</Typography>
        {actions && <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap" }}>{actions}</Stack>}
      </Stack>
      <Stack direction="row" spacing={2.5} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5, overflowX: "auto" }} aria-label="Instance sections">
        {SECTIONS.map(([id, label]) => (
          <Link key={id} href={instanceHref(name, id)} underline={active === id ? "always" : "hover"}
            sx={{ py: 1.25, whiteSpace: "nowrap", color: active === id ? "primary.main" : "text.primary", fontWeight: active === id ? 600 : 400,
              borderBottom: active === id ? 2 : 0, borderColor: "primary.main" }}>
            {label}
          </Link>
        ))}
      </Stack>
    </Box>
  );
}
