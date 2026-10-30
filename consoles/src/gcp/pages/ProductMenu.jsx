/* Navigation menu (hamburger): the products Vyomi simulates, grouped by category. */
import { Box, Chip, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, ListSubheader, Stack, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/esm/Close.js";
import HomeIcon from "@mui/icons-material/esm/Home.js";
import { CATEGORIES, PRODUCTS } from "../services/registry.js";
import { Brand } from "./Brand.jsx";

export default function ProductMenu({ open, onClose, active }) {
  const go = (h) => { location.hash = h; onClose(); };
  return (
    <Drawer open={open} onClose={onClose} PaperProps={{ sx: { width: 300, bgcolor: "background.paper" } }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 1, height: 64 }}>
        <IconButton aria-label="Close navigation menu" onClick={onClose}><CloseIcon /></IconButton>
        <Brand />
      </Stack>
      <Divider />
      <List dense aria-label="Products">
        <ListItemButton selected={!active} onClick={() => go("/")}>
          <ListItemIcon sx={{ minWidth: 40 }}><HomeIcon fontSize="small" /></ListItemIcon>
          <ListItemText primary="Welcome" />
        </ListItemButton>
        {CATEGORIES.map((cat) => {
          const ps = PRODUCTS.filter((p) => p.category === cat);
          if (!ps.length) return null;
          return (
            <Box key={cat}>
              <ListSubheader disableSticky sx={{ lineHeight: "36px", fontWeight: 500, bgcolor: "transparent" }}>{cat}</ListSubheader>
              {ps.map((p) => (
                <ListItemButton key={p.id} selected={active === p.id} onClick={() => go("/" + p.id)} sx={{ borderRadius: "0 20px 20px 0", mr: 1 }}>
                  <ListItemIcon sx={{ minWidth: 40 }}><p.icon fontSize="small" /></ListItemIcon>
                  <ListItemText primary={p.title} />
                  {!p.load && <Chip size="small" variant="outlined" label="classic" sx={{ height: 20, fontSize: 11 }} />}
                </ListItemButton>
              ))}
            </Box>
          );
        })}
      </List>
      <Typography variant="caption" color="text.secondary" sx={{ px: 2, pb: 2 }}>Products marked "classic" open in the classic Vyomi console until their v4 module ships.</Typography>
    </Drawer>
  );
}
