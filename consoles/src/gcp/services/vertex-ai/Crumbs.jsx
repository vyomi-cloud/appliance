/* Breadcrumb row above the content card ("Agent Platform / Models / Model Garden"), as in the native console. */
import { Breadcrumbs, Typography } from "@mui/material";
import { Link } from "../../link.jsx";

export default function Crumbs({ trail }) {
  return (
    <Breadcrumbs aria-label="breadcrumb" separator="/" sx={{ fontSize: 14, mb: 1 }} data-testid="crumbs">
      {trail.map((c, i) => (c.href && i < trail.length - 1
        ? <Link key={c.text} href={c.href} underline="hover" color="text.primary">{c.text}</Link>
        : <Typography key={c.text} fontSize={14} color="text.primary">{c.text}</Typography>))}
    </Breadcrumbs>
  );
}
