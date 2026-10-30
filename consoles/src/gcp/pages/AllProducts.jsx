/* #/products — every product Vyomi's GCP lens knows, by category ("View all products"). */
import { Box, Link, Paper, Stack, Typography } from "@mui/material";
import { CATEGORIES, PRODUCTS, classicHref } from "../services/registry.js";

export default function AllProducts() {
  return (
    <Box>
      <Typography variant="h1" component="h1" sx={{ mb: 2, fontSize: 24 }}>All products</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr", lg: "1fr 1fr 1fr" }, gap: 2 }}>
        {CATEGORIES.map((cat) => {
          const ps = PRODUCTS.filter((p) => p.category === cat);
          if (!ps.length) return null;
          return (
            <Paper key={cat} variant="outlined" sx={{ borderRadius: 2, p: 2 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 500, mb: 1 }}>{cat}</Typography>
              <Stack spacing={1.25}>
                {ps.map((p) => (
                  <Stack key={p.id} direction="row" spacing={1.5} alignItems="flex-start">
                    <p.icon fontSize="small" sx={{ color: "text.secondary", mt: 0.25 }} />
                    <Box>
                      <Link href={p.load ? `#/${p.id}` : classicHref(p.classic)} underline="hover" variant="body2">{p.title}</Link>
                      <Typography variant="caption" display="block" color="text.secondary">{p.description}{p.load ? "" : " · classic console"}</Typography>
                    </Box>
                  </Stack>
                ))}
              </Stack>
            </Paper>
          );
        })}
      </Box>
    </Box>
  );
}
