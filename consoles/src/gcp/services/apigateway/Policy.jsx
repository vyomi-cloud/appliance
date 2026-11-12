/* A config's security schemes and quota limits, shown from the policy the control plane parsed out of the stored OpenAPI document. */
import { Chip, Typography } from "@mui/material";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { Section } from "../../kit/common.jsx";

const none = (t) => <Typography variant="body2" color="text.secondary">{t}</Typography>;
const schemeDetail = (s) => s.type === "apiKey" ? `API key in ${s.in} "${s.keyName}"`
  : s.type === "oauth2" ? `JWT issuer ${s.issuer}${s.audiences ? `, audiences ${s.audiences}` : ""}${s.jwksUri ? `, JWKS ${s.jwksUri}` : ""}` : s.type;

export default function Policy({ policy }) {
  const p = policy || {};
  const schemes = p.securityDefinitions || [], limits = p.quotaLimits || [];
  const ops = (p.operations || []).filter((o) => o.security.length || Object.keys(o.metricCosts).length);
  return (
    <>
      <Section title="Security schemes" description="From securityDefinitions; an operation is protected by its own security, else the document's top-level security.">
        <ResourceTable resourceName="security schemes" items={schemes} rowKey={(s) => s.name}
          columns={[{ id: "n", header: "Scheme", cell: (s) => s.name }, { id: "t", header: "Type", cell: (s) => s.type }, { id: "d", header: "Details", cell: schemeDetail },
            { id: "top", header: "Applies", cell: (s) => (p.security || []).some((r) => r.includes(s.name)) ? <Chip size="small" color="primary" label="All operations" /> : "Per operation" }]}
          empty={none("This config defines no security schemes: every route is open.")} />
      </Section>
      <Section title="Quota limits" description="From x-google-management; an operation consumes a metric through x-google-quota metricCosts.">
        <ResourceTable resourceName="quota limits" items={limits} rowKey={(l) => l.name}
          columns={[{ id: "n", header: "Limit", cell: (l) => l.name }, { id: "m", header: "Metric", cell: (l) => l.metric }, { id: "u", header: "Unit", cell: (l) => l.unit },
            { id: "v", header: "Values", cell: (l) => Object.entries(l.values || {}).map(([k, v]) => `${k}: ${v}`).join(", ") }]}
          empty={none("This config defines no quota limits.")} />
      </Section>
      {ops.length > 0 && <Section title="Per-operation policy">
        <ResourceTable resourceName="operations" items={ops} rowKey={(o) => o.operationId}
          columns={[{ id: "o", header: "Operation", cell: (o) => `${o.method} ${o.path}` },
            { id: "s", header: "Security", cell: (o) => o.security.map((r) => r.join(" + ") || "(none)").join(" or ") || "—" },
            { id: "c", header: "Metric costs", cell: (o) => Object.entries(o.metricCosts).map(([k, v]) => `${k}: ${v}`).join(", ") || "—" }]} />
      </Section>}
    </>
  );
}
