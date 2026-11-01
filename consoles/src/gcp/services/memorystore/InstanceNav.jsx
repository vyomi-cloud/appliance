/* Shared instance-scoped header + sub-navigation strip, same pattern as Cloud SQL's
 * InstanceNav: the real console swaps the left nav for instance-scoped items once an
 * instance is open; Vyomi renders the same destinations as a link strip under the
 * instance name so each one is still its own route (and its own ui-spec page). */
import { Box, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { Link, hashHref } from "../../link.jsx";

export const SECTIONS = [
  ["overview", "Overview"], ["connections", "Connections"], ["configuration", "Configuration"],
  ["nodes", "Nodes"], ["maintenance", "Maintenance"],
];

export const instanceHref = (location, id, section = "overview") => hashHref("memorystore", "instances", location, id, section);

export default function InstanceNav({ location, id, active, actions }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ minHeight: 48, flexWrap: "wrap", rowGap: 1 }}>
        <IconButton aria-label="Back to instances" href="#/memorystore"><ArrowBackIcon /></IconButton>
        <Typography variant="h1" component="h1">{id}</Typography>
        {actions && <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap" }}>{actions}</Stack>}
      </Stack>
      <Stack direction="row" spacing={2.5} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5, overflowX: "auto" }} aria-label="Instance sections">
        {SECTIONS.map(([sid, label]) => (
          <Link key={sid} href={instanceHref(location, id, sid)} underline={active === sid ? "always" : "hover"}
            sx={{ py: 1.25, whiteSpace: "nowrap", color: active === sid ? "primary.main" : "text.primary", fontWeight: active === sid ? 600 : 400,
              borderBottom: active === sid ? 2 : 0, borderColor: "primary.main" }}>
            {label}
          </Link>
        ))}
      </Stack>
    </Box>
  );
}
