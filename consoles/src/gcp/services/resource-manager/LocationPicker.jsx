/* "Select a destination" tree: the organization and its folders (the native console's Browse dialog). */
import { useMemo } from "react";
import { Box, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import FolderOutlinedIcon from "@mui/icons-material/esm/FolderOutlined.js";
import BusinessOutlinedIcon from "@mui/icons-material/esm/BusinessOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

export default function LocationPicker({ value, onChange, exclude }) {
  const { data } = useAsync(async () => ({ org: await api.getOrg(), folders: await api.allFolders() }), []);
  const rows = useMemo(() => {
    if (!data?.org) return [];
    const out = [{ name: data.org.name, label: data.org.displayName, depth: 0, org: true }];
    const walk = (parent, depth) => data.folders.filter((f) => f.parent === parent && f.name !== exclude)
      .sort((a, b) => a.displayName.localeCompare(b.displayName))
      .forEach((f) => { out.push({ name: f.name, label: f.displayName, depth }); walk(f.name, depth + 1); });
    walk(data.org.name, 1);
    return out;
  }, [data, exclude]);
  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>Select a parent organization or folder</Typography>
      <List dense role="listbox" aria-label="Parent organization or folder" sx={{ maxHeight: 260, overflow: "auto", border: 1, borderColor: "divider", borderRadius: 1, mt: 1 }}>
        {rows.map((r) => (
          <ListItemButton key={r.name} role="option" aria-selected={value === r.name} selected={value === r.name} onClick={() => onChange(r.name)} sx={{ pl: 1 + r.depth * 2.5 }}>
            {r.org ? <BusinessOutlinedIcon fontSize="small" sx={{ mr: 1 }} /> : <FolderOutlinedIcon fontSize="small" sx={{ mr: 1 }} />}
            <ListItemText primary={r.label} />
          </ListItemButton>
        ))}
      </List>
    </Box>
  );
}
