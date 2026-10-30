/* Small shared pieces: honest "not simulated" state, key-value details, status, errors. */
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Alert from "@cloudscape-design/components/alert";
import Badge from "@cloudscape-design/components/badge";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { VyomiMark } from "../../common/VyomiMark.jsx";

/** A feature the real console has but Vyomi does not back with a real backend.
 *  Rendered visibly — a fake success would be a UI-conformance failure. */
export function NotSimulated({ feature, note }) {
  return (
    <Box padding="l" textAlign="center" color="text-body-secondary" data-vyomi-not-simulated={feature}>
      <SpaceBetween size="xs">
        <Badge color="grey">Not simulated in <VyomiMark /></Badge>
        <Box variant="p" color="inherit">{feature} isn't backed by a <VyomiMark /> backend yet.</Box>
        {note && <Box variant="small" color="inherit">{note}</Box>}
      </SpaceBetween>
    </Box>
  );
}

export function NotSimulatedContainer({ title, feature, note }) {
  // data-vyomi-gap-box marks the exact boundary of a declared gap for the UI-conformance checker.
  return (
    <div data-vyomi-gap-box="">
    <Container header={<Header variant="h2">{title}</Header>}>
      <NotSimulated feature={feature || title} note={note} />
    </Container>
    </div>
  );
}

/** Details container: label/value pairs in up to 4 columns, like every console overview. */
export function KeyValue({ title, actions, columns = 3, items }) {
  const cols = Array.from({ length: columns }, () => []);
  items.forEach((it, i) => cols[i % columns].push(it));
  return (
    <Container header={title && <Header variant="h2" actions={actions}>{title}</Header>}>
      <ColumnLayout columns={columns} variant="text-grid">
        {cols.map((c, i) => (
          <SpaceBetween size="l" key={i}>
            {c.map(([label, value]) => (
              <div key={label}>
                <Box variant="awsui-key-label">{label}</Box>
                <div>{value === undefined || value === null || value === "" ? "-" : value}</div>
              </div>
            ))}
          </SpaceBetween>
        ))}
      </ColumnLayout>
    </Container>
  );
}

export const Status = ({ ok, children, type }) => (
  <StatusIndicator type={type || (ok ? "success" : "stopped")}>{children}</StatusIndicator>
);

export const ErrorAlert = ({ error, header }) =>
  error ? <Alert type="error" header={header || error.code || "Error"}>{error.message}</Alert> : null;

export const fmtDate = (v) => {
  if (!v) return "-";
  const d = typeof v === "number" ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
  return isNaN(d) ? String(v) : d.toLocaleString(undefined, { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short" });
};

export const fmtBytes = (n) => {
  n = Number(n || 0);
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(1) : n} ${u[i]}`;
};
