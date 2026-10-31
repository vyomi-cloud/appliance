/* Create an HTTP / WebSocket / GraphQL / gRPC API, scoped to an API Management service:
 * Basic / Full (the real portal's "Full" toggle just shows every field on one screen — Vyomi
 * has no fields that are Full-only) → one native ARM PUT (properties.apiType — a real,
 * documented APIM field — takes the non-HTTP flows as-is, no backend-specific code needed),
 * optionally associated with Products. WebSocket/GraphQL/gRPC share this wizard, parameterized
 * by apiType (see index.jsx's /apis/create/:apitype route) — only the backend-URL field's
 * label and the protocol it stores differ (azure.apim.apis.createflows). */
import { useState } from "react";
import { Checkbox, Input, Radio, RadioGroup, Select, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9-]{0,255}$/;

const TYPE_META = {
  http: { label: "HTTP", title: "Create an HTTP API", urlLabel: "Web service URL", scheme: true, protocols: (s) => s === "Both" ? ["http", "https"] : [s.toLowerCase()] },
  websocket: { label: "WebSocket", title: "Create a WebSocket API", urlLabel: "WebSocket URL", scheme: false, protocols: () => ["wss"] },
  graphql: { label: "GraphQL", title: "Create a GraphQL API", urlLabel: "GraphQL API endpoint", scheme: false, protocols: () => ["https"] },
  grpc: { label: "gRPC", title: "Create a gRPC API", urlLabel: "gRPC server URL", scheme: false, protocols: () => ["grpc"] },
};

export default function CreateHttpApi({ params }) {
  const { rg, name: svc, apitype } = params;
  const meta = TYPE_META[apitype] || TYPE_META.http;
  const notify = useNotify();
  const self = `#/apim/${encodeURIComponent(rg)}/${encodeURIComponent(svc)}`;
  const products = useAsync(() => api.Products.list(rg, svc), [rg, svc]);
  const existing = useAsync(() => api.Apis.list(rg, svc), [rg, svc]);
  const [f, setF] = useState({
    displayName: "", name: "", serviceUrl: "", path: "", description: "",
    scheme: "HTTPS", product: "", versioned: false,
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));

  const errors = () => {
    const e = [];
    if (!f.displayName.trim()) e.push("Display name is required.");
    if (!NAME_RE.test(f.name)) e.push("Name must start with a letter or number and contain only letters, numbers and hyphens.");
    else if ((existing.data || []).some((a) => a.name.toLowerCase() === f.name.toLowerCase())) e.push(`An API named "${f.name}" already exists.`);
    return e;
  };

  const body = () => ({
    properties: {
      displayName: f.displayName,
      serviceUrl: f.serviceUrl || undefined,
      path: f.path,
      description: f.description || undefined,
      apiType: meta === TYPE_META.http ? undefined : apitype,
      protocols: meta.scheme ? (f.scheme === "Both" ? ["http", "https"] : [f.scheme.toLowerCase()]) : meta.protocols(),
      apiRevision: "1",
      subscriptionRequired: true,
      isCurrent: true,
    },
  });

  const fields = (
    <>
      <FormSection title={meta.title}>
        <FormRow label="Display name" required htmlFor="ha-display"><Input id="ha-display" value={f.displayName} onChange={(_, d) => setF((x) => ({ ...x, displayName: d.value, name: x.name || d.value.toLowerCase().replace(/[^a-z0-9-]+/g, "-") }))} aria-label="Display name" style={{ width: "100%" }} /></FormRow>
        <FormRow label="Name" required htmlFor="ha-name"><Input id="ha-name" value={f.name} onChange={set("name")} aria-label="Name" style={{ width: "100%" }} /></FormRow>
        <FormRow label={meta.urlLabel} htmlFor="ha-url"><Input id="ha-url" value={f.serviceUrl} onChange={set("serviceUrl")} placeholder={meta.scheme ? "https://..." : "wss://..."} aria-label={meta.urlLabel} style={{ width: "100%" }} /></FormRow>
        <FormRow label="API URL suffix" htmlFor="ha-suffix"><Input id="ha-suffix" value={f.path} onChange={set("path")} aria-label="API URL suffix" style={{ width: "100%" }} /></FormRow>
        <FormRow label="Description" htmlFor="ha-desc"><Textarea id="ha-desc" value={f.description} onChange={set("description")} aria-label="Description" style={{ width: "100%" }} /></FormRow>
        {meta.scheme && (
          <FormRow label="URL scheme">
            <RadioGroup value={f.scheme} onChange={set("scheme")} aria-label="URL scheme" layout="horizontal">
              <Radio value="HTTP" label="HTTP" /><Radio value="HTTPS" label="HTTPS" /><Radio value="Both" label="Both" />
            </RadioGroup>
          </FormRow>
        )}
        <FormRow label="Products" htmlFor="ha-product">
          <Select id="ha-product" value={f.product} onChange={set("product")} aria-label="Products">
            <option value="">None</option>
            {(products.data || []).map((p) => <option key={p.name} value={p.name}>{p.properties?.displayName || p.name}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Version this API?"><Checkbox checked={f.versioned} onChange={(_, d) => setF((x) => ({ ...x, versioned: !!d.checked }))} aria-label="Version this API?" /></FormRow>
      </FormSection>
      <NotSimulatedContainer title="Gateways" feature="Restricting a new API to specific self-hosted gateways" note="New APIs are always reachable on the managed gateway." />
    </>
  );

  const review = () => {
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return dl([["Display name", f.displayName || "--"], ["Name", f.name || "--"], [meta.urlLabel, f.serviceUrl || "--"],
      ["API URL suffix", f.path || "--"], ...(meta.scheme ? [["URL scheme", f.scheme]] : []), ["Product", f.product || "None"]]);
  };

  const onCreate = async () => {
    try {
      await api.Apis.put(rg, svc, f.name, body());
      if (f.product) await api.addProductApi(rg, svc, f.product, f.name);
      notify.success(`API '${f.displayName}' was created.`, "Create succeeded");
      navigate("apim", rg, svc, "apis");
    } catch (e) { notify.error(e, "Create failed"); }
  };

  return (
    <CreateWizard
      title={meta.title} closeHref={`${self}/apis`} glyph={<Glyph id="apim" />}
      tabs={[
        { id: "basic", label: "Basic", content: fields, validate: errors },
        { id: "full", label: "Full", content: fields },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
