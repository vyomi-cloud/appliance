/* Vyomi wordmark for the GCP lens top bar (no third-party logos or marks). */
import { Box, Stack, Typography } from "@mui/material";

export function Brand() {
  return (
    <Stack component="a" href="#/" direction="row" alignItems="center" spacing={1} sx={{ color: "text.primary", textDecoration: "none", px: 0.5 }} aria-label="Vyomi home">
      <Box aria-hidden sx={{ width: 26, height: 26, borderRadius: "8px", display: "grid", placeItems: "center", color: "#fff", fontWeight: 700, fontSize: 15,
        background: "linear-gradient(135deg, #1a73e8 0%, #0b57d0 55%, #00639b 100%)" }}>V</Box>
      <Typography sx={{ fontSize: 20, fontWeight: 500, letterSpacing: -0.2 }}>Vyomi</Typography>
      <Typography sx={{ fontSize: 13, color: "text.secondary", display: { xs: "none", md: "block" } }}>GCP lens</Typography>
    </Stack>
  );
}
