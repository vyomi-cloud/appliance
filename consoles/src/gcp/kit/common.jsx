/* Small shared pieces for the GCP lens: honest "not simulated" state, page header,
 * key-value details, sections, errors, formatters.
 *
 * CONTRACT (UI conformance): every declared gap carries `data-vyomi-not-simulated="<feature>"`
 * and sits in an element whose class contains "container", so the checker attributes all
 * of the panel's text (title included) to an honest gap — same as the AWS lens. */
import { Alert, Box, Chip, Divider, Paper, Stack, Typography } from "@mui/material";

/** A feature the real console has but Vyomi does not back with a real backend. */
export function NotSimulated({ feature, note, compact }) {
  return (
    <Box className="vyomi-ns-container" data-vyomi-not-simulated={feature}
      sx={{ p: compact ? 1.5 : 3, textAlign: compact ? "left" : "center", color: "text.secondary" }}>
      <Stack spacing={0.75} alignItems={compact ? "flex-start" : "center"}>
        <Chip size="small" label="Not simulated in Vyomi" sx={{ fontWeight: 500 }} />
        <Typography variant="body2" color="inherit">{feature} isn't backed by a Vyomi backend yet.</Typography>
        {note && <Typography variant="caption" color="inherit">{note}</Typography>}
      </Stack>
    </Box>
  );
}

/** A whole section (title + body) that is a declared gap. */
export function NotSimulatedContainer({ title, feature, note, description }) {
  return (
    <Section title={title} description={description} className="vyomi-container" dataNs={feature || title}>
      <NotSimulated feature={feature || title} note={note} compact />
    </Section>
  );
}

/** Bordered content section with a title row, like the console's cards/sections. */
export function Section({ title, description, actions, children, className, dataNs, noPad }) {
  return (
    <Paper variant="outlined" className={className} {...(dataNs ? { "data-vyomi-not-simulated": dataNs } : {})}
      sx={{ borderRadius: 2, overflow: "hidden" }}>
      {(title || actions) && (
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2.5, pt: 2, pb: description ? 0.5 : 1.5 }} spacing={2}>
          <Typography variant="h3" component="h2">{title}</Typography>
          {actions && <Stack direction="row" spacing={1}>{actions}</Stack>}
        </Stack>
      )}
      {description && <Typography variant="body2" color="text.secondary" sx={{ px: 2.5, pb: 1.5 }}>{description}</Typography>}
      <Box sx={noPad ? {} : { px: 2.5, pb: 2.5 }}>{children}</Box>
    </Paper>
  );
}

/** The console's page header: title row with action buttons, a divider under it. */
export function PageHeader({ title, back, actions, children }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ minHeight: 56, flexWrap: "wrap", rowGap: 1 }}>
        {back}
        <Typography variant="h1" component="h1" sx={{ mr: 2 }}>{title}</Typography>
        {actions && <Stack direction="row" spacing={0.5} alignItems="center" sx={{ flexWrap: "wrap" }}>{actions}</Stack>}
      </Stack>
      <Divider sx={{ mx: -3 }} />
      {children}
    </Box>
  );
}

/** Label/value pairs, the details layout the console uses on Configuration tabs. */
export function KeyValue({ items, labelWidth = 240 }) {
  return (
    <Box component="dl" sx={{ m: 0, display: "grid", gridTemplateColumns: { xs: "1fr", sm: `${labelWidth}px 1fr` }, columnGap: 3, rowGap: 1.5 }}>
      {items.filter(Boolean).map(([label, value, action]) => (
        <Box key={label} sx={{ display: "contents" }}>
          <Typography component="dt" variant="body2" color="text.secondary">{label}</Typography>
          <Box component="dd" sx={{ m: 0, display: "flex", alignItems: "center", gap: 1, minWidth: 0, wordBreak: "break-word" }}>
            <Typography component="span" variant="body2">{value === undefined || value === null || value === "" ? "—" : value}</Typography>
            {action}
          </Box>
        </Box>
      ))}
    </Box>
  );
}

export const ErrorAlert = ({ error, title }) =>
  error ? <Alert severity="error" sx={{ mb: 2 }}><b>{title || error.code || "Error"}</b>{": "}{error.message}</Alert> : null;

export const fmtDate = (v) => {
  if (!v) return "—";
  const d = new Date(v);
  return isNaN(d) ? String(v) : d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
};

export const fmtBytes = (n) => {
  n = Number(n || 0);
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(1) : n} ${u[i]}`;
};

export const fmtDuration = (secs) => {
  secs = Number(secs || 0);
  for (const [n, u] of [[31536000, "year"], [86400, "day"], [3600, "hour"], [60, "minute"]]) {
    if (secs >= n && secs % n === 0) return `${secs / n} ${u}${secs / n === 1 ? "" : "s"}`;
  }
  return `${secs} seconds`;
};
