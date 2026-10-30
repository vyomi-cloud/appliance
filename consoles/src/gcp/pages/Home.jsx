/* Welcome page: project info, quick access to products, and what Vyomi backs. */
import { Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { CATEGORIES, PRODUCTS } from "../services/registry.js";
import { useProject } from "../project.js";
import { KeyValue, Section } from "../kit/common.jsx";

export default function Home() {
  const project = useProject();
  return (
    <Box>
      <Typography variant="h1" component="h1" sx={{ fontSize: 28, mb: 0.5 }}>Welcome</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        You're working in <b>{project}</b>. Everything you do here runs against your local Vyomi simulator and is visible to your SDKs, gcloud and gsutil.
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 3, flexWrap: "wrap", rowGap: 1 }}>
        <Button variant="outlined" startIcon={<AddIcon />} href="#/storage/create-bucket">Create a storage bucket</Button>
        <Button variant="outlined" href="#/storage/browser">View buckets</Button>
      </Stack>
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "340px 1fr" }, alignItems: "start" }}>
        <Section title="Project info">
          <KeyValue labelWidth={120} items={[["Project name", project], ["Project ID", project], ["Backend", "Vyomi simulator (local)"]]} />
        </Section>
        <Section title="Products" description="Products with a v4 console open here; the rest open in the classic Vyomi console.">
          <Stack spacing={2.5}>
            {CATEGORIES.map((cat) => {
              const ps = PRODUCTS.filter((p) => p.category === cat);
              if (!ps.length) return null;
              return (
                <Box key={cat}>
                  <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>{cat}</Typography>
                  <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", lg: "1fr 1fr 1fr" } }}>
                    {ps.map((p) => (
                      <Paper key={p.id} component="a" href={`#/${p.id}`} variant="outlined"
                        sx={{ p: 1.5, display: "flex", gap: 1.5, alignItems: "flex-start", textDecoration: "none", color: "inherit", borderRadius: 2, "&:hover": { bgcolor: "action.hover" } }}>
                        <p.icon fontSize="small" color="primary" sx={{ mt: 0.25 }} />
                        <Box sx={{ minWidth: 0 }}>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Typography variant="body2" sx={{ fontWeight: 500, color: "primary.main" }}>{p.title}</Typography>
                            {!p.load && <Chip size="small" variant="outlined" label="classic" sx={{ height: 18, fontSize: 11 }} />}
                          </Stack>
                          <Typography variant="caption" color="text.secondary">{p.description}</Typography>
                        </Box>
                      </Paper>
                    ))}
                  </Box>
                </Box>
              );
            })}
          </Stack>
        </Section>
      </Box>
    </Box>
  );
}
