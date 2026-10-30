/* #/products — "All products", laid out like the native console: sticky category nav on the
 * left; per category a title + blurb and a table (☆ · Name · Description · docs · ▾ sub-pages).
 * Favourites are shared with the navigation menu. Sub-page lists come from the reviewed
 * ui-spec navs (services/subpages.json, generated). */
import { Fragment, useState } from "react";
import { Box, Collapse, IconButton, Link, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from "@mui/material";
import StarIcon from "@mui/icons-material/esm/Star.js";
import StarBorderIcon from "@mui/icons-material/esm/StarBorder.js";
import ArticleIcon from "@mui/icons-material/esm/ArticleOutlined.js";
import ExpandMoreIcon from "@mui/icons-material/esm/ExpandMore.js";
import { CATEGORIES, PRODUCTS, classicHref } from "../services/registry.js";
import SUBPAGES from "../services/subpages.json";

// Our own one-line summaries of each category (what Vyomi offers in it).
const BLURBS = {
  Compute: "Run virtual machines and containers",
  Storage: "Store objects and files",
  Databases: "Managed relational and NoSQL databases",
  Networking: "Networks, subnets, firewalls and routes",
  Serverless: "Run code and containers without managing servers",
  "Integration Services": "Messaging and scheduled jobs between services",
  Security: "Keys, secrets and encryption",
  Management: "Identity, access and administration",
  "CI/CD": "Store and manage build artifacts",
  Observability: "Metrics, dashboards, alerts and logs",
};

const read = (k, d) => { try { return JSON.parse(localStorage.getItem(`vyomi.v4.gcp.${k}`)) ?? d; } catch { return d; } };
const write = (k, v) => { try { localStorage.setItem(`vyomi.v4.gcp.${k}`, JSON.stringify(v)); } catch {} };
const anchor = (c) => `cat-${c.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
const openHref = (p) => (p.load ? `#/${p.id}` : classicHref(p.classic));

export default function AllProducts() {
  const [favs, setFavs] = useState(() => read("favorites", []));
  const [open, setOpen] = useState({});
  const cats = CATEGORIES.filter((c) => PRODUCTS.some((p) => p.category === c));
  const toggleFav = (id) => { const f = favs.includes(id) ? favs.filter((x) => x !== id) : [...favs, id]; setFavs(f); write("favorites", f); };

  return (
    <Box sx={{ display: "flex", gap: 3, alignItems: "flex-start" }}>
      <Box component="nav" aria-label="Product categories" sx={{ width: 220, flexShrink: 0, position: "sticky", top: 72, display: { xs: "none", md: "block" } }}>
        {cats.map((c) => (
          <Link key={c} href={`#/products`} underline="none" onClick={(e) => { e.preventDefault(); document.getElementById(anchor(c))?.scrollIntoView({ behavior: "smooth", block: "start" }); }}
            sx={{ display: "block", px: 2, py: 0.9, color: "text.primary", borderRadius: "0 20px 20px 0", "&:hover": { bgcolor: "action.hover" } }}>
            <Typography variant="body2">{c}</Typography>
          </Link>
        ))}
      </Box>

      <Box sx={{ flex: 1, minWidth: 0, maxWidth: 1000 }}>
        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2} sx={{ mb: 4, mt: 1 }}>
          <Box>
            <Typography variant="h1" component="h1" sx={{ fontSize: 28, fontWeight: 400, mb: 1 }}>All products</Typography>
            <Typography variant="body1" color="text.secondary">Explore the Google Cloud products Vyomi simulates at a glance</Typography>
          </Box>
          <Paper variant="outlined" sx={{ p: 2, maxWidth: 260, bgcolor: "action.hover", borderRadius: 2 }} data-vyomi-not-simulated="Marketplace">
            <Typography variant="body2" sx={{ fontWeight: 500 }}>Marketplace</Typography>
            <Typography variant="caption" color="text.secondary">Third-party Marketplace products aren't simulated in Vyomi.</Typography>
          </Paper>
        </Stack>

        {cats.map((c) => (
          <Box key={c} id={anchor(c)} sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "220px 1fr" }, gap: 3, mb: 5, scrollMarginTop: 80 }}>
            <Box>
              <Typography variant="h2" sx={{ fontSize: 18, fontWeight: 400, mb: 1 }}>{c}</Typography>
              <Typography variant="body2" color="text.secondary">{BLURBS[c]}</Typography>
            </Box>
            <Table size="small" aria-label={`${c} products`} sx={{ tableLayout: "fixed" }}>
              <TableHead>
                <TableRow sx={{ bgcolor: "action.hover" }}>
                  <TableCell sx={{ width: 40 }} />
                  <TableCell sx={{ fontWeight: 500, width: "32%" }}>Name</TableCell>
                  <TableCell sx={{ fontWeight: 500 }}>Description</TableCell>
                  <TableCell sx={{ width: 40 }} />
                  <TableCell sx={{ width: 48 }} />
                </TableRow>
              </TableHead>
              <TableBody>
                {PRODUCTS.filter((p) => p.category === c).map((p) => {
                  const subs = SUBPAGES[p.id] || [];
                  const isOpen = !!open[p.id];
                  return (
                    <Fragment key={p.id}>
                      <TableRow hover>
                        <TableCell>
                          <IconButton size="small" aria-label={`${favs.includes(p.id) ? "Unpin" : "Pin"} ${p.title}`} onClick={() => toggleFav(p.id)}>
                            {favs.includes(p.id) ? <StarIcon fontSize="small" sx={{ color: "primary.main" }} /> : <StarBorderIcon fontSize="small" />}
                          </IconButton>
                        </TableCell>
                        <TableCell><Link href={openHref(p)} underline="always" variant="body2">{p.title}</Link></TableCell>
                        <TableCell><Typography variant="body2">{p.description}{p.load ? "" : " · classic console"}</Typography></TableCell>
                        <TableCell>
                          <Tooltip title="Documentation"><IconButton size="small" component="a" href="https://vyomi.cloud" target="_blank" rel="noopener noreferrer" aria-label={`${p.title} documentation`}><ArticleIcon fontSize="small" /></IconButton></Tooltip>
                        </TableCell>
                        <TableCell>
                          {subs.length > 0 && (
                            <IconButton size="small" aria-label={`${isOpen ? "Collapse" : "Expand"} ${p.title}`} aria-expanded={isOpen} onClick={() => setOpen({ ...open, [p.id]: !isOpen })}>
                              <ExpandMoreIcon fontSize="small" sx={{ transform: isOpen ? "rotate(180deg)" : "none", transition: "transform .15s" }} />
                            </IconButton>
                          )}
                        </TableCell>
                      </TableRow>
                      {subs.length > 0 && (
                        <TableRow>
                          <TableCell colSpan={5} sx={{ py: 0, borderBottom: isOpen ? undefined : 0 }}>
                            <Collapse in={isOpen} unmountOnExit>
                              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 0.75, py: 1.5, pl: 7 }}>
                                {subs.map((s) => <Link key={s} href={openHref(p)} underline="hover" variant="body2">{s}</Link>)}
                              </Box>
                            </Collapse>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
