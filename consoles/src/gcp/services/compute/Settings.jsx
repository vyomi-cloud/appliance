/* Settings — the console's default region/zone preference. Needs no backend: it's a local
 * console preference, persisted in this browser (same pattern as gcp/project.js). */
import { useState } from "react";
import { Box, FormControl, InputLabel, MenuItem, Select, Snackbar } from "@mui/material";
import { PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const KEY = "vyomi.v4.gcp.compute.defaultLocation";
const read = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
const write = (v) => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch {} };

export default function Settings() {
  const saved = read();
  const [region, setRegion] = useState(saved.region || api.DEFAULT_REGION);
  const [zone, setZone] = useState(saved.zone || api.DEFAULT_ZONE);
  const [savedNow, setSavedNow] = useState(false);

  const update = (r, z) => { setRegion(r); setZone(z); write({ region: r, zone: z }); setSavedNow(true); };

  return (
    <Box>
      <PageHeader title="Settings" />
      <Section title="Default location">
        <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
          <FormControl sx={{ minWidth: 260 }}>
            <InputLabel id="def-region">Region</InputLabel>
            <Select labelId="def-region" label="Region" value={region} onChange={(e) => update(e.target.value, api.ZONES_BY_REGION[e.target.value]?.[0] || zone)}>
              {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl sx={{ minWidth: 200 }}>
            <InputLabel id="def-zone">Zone</InputLabel>
            <Select labelId="def-zone" label="Zone" value={zone} onChange={(e) => update(region, e.target.value)}>
              {(api.ZONES_BY_REGION[region] || []).map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
            </Select>
          </FormControl>
        </Box>
      </Section>
      <Snackbar open={savedNow} autoHideDuration={2000} onClose={() => setSavedNow(false)} message="Default location saved" />
    </Box>
  );
}
