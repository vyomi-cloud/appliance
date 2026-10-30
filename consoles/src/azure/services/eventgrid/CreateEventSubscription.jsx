/* Create an Event Subscription on a topic: Basic, Filters, Additional Features, Delivery
 * Properties, Advanced Editor → one native ARM PUT, scoped to the topic. */
import { useState } from "react";
import {
  Button, Checkbox, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea,
} from "@fluentui/react-components";
import { Add20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import CreateWizard, { FormRow, FormSection } from "../../kit/CreateWizard.jsx";
import { Glyph, InfoBar } from "../../kit/common.jsx";
import * as api from "./api.js";

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{1,48}[a-zA-Z0-9]$/;

export default function CreateEventSubscription({ params }) {
  const { rg, name: topic } = params;
  const notify = useNotify();
  const [f, setF] = useState({
    name: "", eventSchema: "Event Grid Schema", eventTypes: "",
    endpointType: "WebHook", endpoint: "",
    subjectFilter: false, subjectBeginsWith: "", subjectEndsWith: "", caseSensitive: false,
    advancedFilters: [{ key: "", operator: "StringContains", value: "" }],
    deadLetter: false, maxDeliveryAttempts: 30, eventTtl: 1440,
    expiration: false, expirationDate: "",
    deliveryHeaders: [{ name: "", value: "", secret: false }],
    advancedJson: "",
  });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const chk = (k) => (_, d) => setF((x) => ({ ...x, [k]: !!d.checked }));

  const basicsErrors = () => {
    const e = [];
    if (!NAME_RE.test(f.name)) e.push("Name must be 3-50 characters: letters, numbers, hyphens, underscores and periods.");
    if (!f.endpointType) e.push("Endpoint Type is required.");
    if (!f.endpoint) e.push("Endpoint is required.");
    return e;
  };

  const basic = (
    <>
      <FormSection title="Event Subscription Details">
        <FormRow label="Name" required htmlFor="es-name">
          <Input id="es-name" value={f.name} onChange={set("name")} aria-label="Name" style={{ width: "100%" }} />
        </FormRow>
        <FormRow label="Event Schema" htmlFor="es-schema">
          <Select id="es-schema" value={f.eventSchema} onChange={set("eventSchema")} aria-label="Event Schema">
            <option value="Event Grid Schema">Event Grid Schema</option>
            <option value="Cloud Event Schema v1.0">Cloud Event Schema v1.0</option>
          </Select>
        </FormRow>
      </FormSection>
      <FormSection title="Topic Details">
        <FormRow label="Topic Type"><Input readOnly value="Microsoft.EventGrid.Topics" aria-label="Topic Type" /></FormRow>
        <FormRow label="Source Resource"><Input readOnly value={topic} aria-label="Source Resource" /></FormRow>
      </FormSection>
      <FormSection title="Event Types">
        <FormRow label="Filter to Event Types" htmlFor="es-types" info="Comma-separated event type names; leave blank for all event types.">
          <Input id="es-types" value={f.eventTypes} onChange={set("eventTypes")} placeholder="e.g. Microsoft.Storage.BlobCreated" aria-label="Filter to Event Types" style={{ width: "100%" }} />
        </FormRow>
      </FormSection>
      <FormSection title="Endpoint Details">
        <FormRow label="Endpoint Type" required htmlFor="es-endpointtype">
          <Select id="es-endpointtype" value={f.endpointType} onChange={set("endpointType")} aria-label="Endpoint Type">
            {api.ENDPOINT_TYPES.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
          </Select>
        </FormRow>
        <FormRow label="Endpoint" required htmlFor="es-endpoint" info="Configure an endpoint">
          <Input id="es-endpoint" value={f.endpoint} onChange={set("endpoint")} placeholder="https://..." aria-label="Endpoint" style={{ width: "100%" }} />
        </FormRow>
      </FormSection>
    </>
  );

  const filters = (
    <>
      <FormSection title="Subject Filters">
        <FormRow label="Enable subject filtering"><Checkbox checked={f.subjectFilter} onChange={chk("subjectFilter")} aria-label="Enable subject filtering" /></FormRow>
        <FormRow label="Subject Begins With" htmlFor="es-begins"><Input id="es-begins" disabled={!f.subjectFilter} value={f.subjectBeginsWith} onChange={set("subjectBeginsWith")} aria-label="Subject Begins With" /></FormRow>
        <FormRow label="Subject Ends With" htmlFor="es-ends"><Input id="es-ends" disabled={!f.subjectFilter} value={f.subjectEndsWith} onChange={set("subjectEndsWith")} aria-label="Subject Ends With" /></FormRow>
        <FormRow label="Case-sensitive subject matching"><Checkbox checked={f.caseSensitive} disabled={!f.subjectFilter} onChange={chk("caseSensitive")} aria-label="Case-sensitive subject matching" /></FormRow>
      </FormSection>
      <FormSection title="Advanced Filters">
        <FormRow label="Advanced filters">
          <Table size="small" aria-label="Advanced filters" style={{ maxWidth: 640 }}>
            <TableHeader><TableRow><TableHeaderCell>Key</TableHeaderCell><TableHeaderCell>Operator</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell style={{ width: 40 }} /></TableRow></TableHeader>
            <TableBody>
              {f.advancedFilters.map((r, i) => (
                <TableRow key={i}>
                  <TableCell><Input size="small" value={r.key} onChange={(_, d) => setF((x) => ({ ...x, advancedFilters: x.advancedFilters.map((a, j) => (j === i ? { ...a, key: d.value } : a)) }))} aria-label={`Advanced filter key ${i + 1}`} /></TableCell>
                  <TableCell>
                    <Select size="small" value={r.operator} onChange={(_, d) => setF((x) => ({ ...x, advancedFilters: x.advancedFilters.map((a, j) => (j === i ? { ...a, operator: d.value } : a)) }))} aria-label={`Advanced filter operator ${i + 1}`}>
                      {["NumberIn", "NumberNotIn", "NumberLessThan", "NumberGreaterThan", "BoolEquals", "StringContains", "StringBeginsWith", "StringEndsWith", "StringIn"].map((o) => <option key={o} value={o}>{o}</option>)}
                    </Select>
                  </TableCell>
                  <TableCell><Input size="small" value={r.value} onChange={(_, d) => setF((x) => ({ ...x, advancedFilters: x.advancedFilters.map((a, j) => (j === i ? { ...a, value: d.value } : a)) }))} aria-label={`Advanced filter value ${i + 1}`} /></TableCell>
                  <TableCell>{i < f.advancedFilters.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete filter" onClick={() => setF((x) => ({ ...x, advancedFilters: x.advancedFilters.filter((_, j) => j !== i) }))} />}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Button style={{ marginTop: 8 }} icon={<Add20Regular />} onClick={() => setF((x) => ({ ...x, advancedFilters: [...x.advancedFilters, { key: "", operator: "StringContains", value: "" }] }))}>Add new filter</Button>
        </FormRow>
      </FormSection>
    </>
  );

  const additional = (
    <>
      <FormSection title="Dead-lettering">
        <FormRow label="Enable dead-lettering"><Checkbox checked={f.deadLetter} onChange={chk("deadLetter")} aria-label="Enable dead-lettering" /></FormRow>
        {f.deadLetter && <InfoBar>Stored and returned exactly as configured; Vyomi does not route undeliverable events to a dead-letter blob.</InfoBar>}
      </FormSection>
      <FormSection title="Retry policies">
        <FormRow label="Max event delivery attempts" htmlFor="es-attempts">
          <Input id="es-attempts" type="number" min={1} max={30} value={String(f.maxDeliveryAttempts)} onChange={set("maxDeliveryAttempts")} aria-label="Max event delivery attempts" />
        </FormRow>
        <FormRow label="Event time to live (minutes)" htmlFor="es-ttl">
          <Input id="es-ttl" type="number" min={1} max={1440} value={String(f.eventTtl)} onChange={set("eventTtl")} aria-label="Event time to live (minutes)" />
        </FormRow>
      </FormSection>
      <FormSection title="Event subscription expiration time">
        <FormRow label="Enable expiration time"><Checkbox checked={f.expiration} onChange={chk("expiration")} aria-label="Enable expiration time" /></FormRow>
        {f.expiration && <FormRow label="Expiration date" htmlFor="es-exp"><Input id="es-exp" type="datetime-local" value={f.expirationDate} onChange={set("expirationDate")} aria-label="Expiration date" /></FormRow>}
      </FormSection>
    </>
  );

  const delivery = (
    <FormSection title="Delivery Properties">
      <FormRow label="Header">
        <Table size="small" aria-label="Header" style={{ maxWidth: 640 }}>
          <TableHeader><TableRow><TableHeaderCell>Header name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell>Is secret</TableHeaderCell><TableHeaderCell style={{ width: 40 }} /></TableRow></TableHeader>
          <TableBody>
            {f.deliveryHeaders.map((h, i) => (
              <TableRow key={i}>
                <TableCell><Input size="small" value={h.name} onChange={(_, d) => setF((x) => ({ ...x, deliveryHeaders: x.deliveryHeaders.map((a, j) => (j === i ? { ...a, name: d.value } : a)) }))} aria-label={`Header name ${i + 1}`} /></TableCell>
                <TableCell>Static</TableCell>
                <TableCell><Input size="small" value={h.value} onChange={(_, d) => setF((x) => ({ ...x, deliveryHeaders: x.deliveryHeaders.map((a, j) => (j === i ? { ...a, value: d.value } : a)) }))} aria-label={`Header value ${i + 1}`} /></TableCell>
                <TableCell><Checkbox checked={h.secret} onChange={(_, d) => setF((x) => ({ ...x, deliveryHeaders: x.deliveryHeaders.map((a, j) => (j === i ? { ...a, secret: !!d.checked } : a)) }))} aria-label={`Header ${i + 1} is secret`} /></TableCell>
                <TableCell>{i < f.deliveryHeaders.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete header" onClick={() => setF((x) => ({ ...x, deliveryHeaders: x.deliveryHeaders.filter((_, j) => j !== i) }))} />}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Button style={{ marginTop: 8 }} icon={<Add20Regular />} onClick={() => setF((x) => ({ ...x, deliveryHeaders: [...x.deliveryHeaders, { name: "", value: "", secret: false }] }))}>Add new header</Button>
      </FormRow>
    </FormSection>
  );

  const advancedEditor = (
    <FormSection title="Advanced Editor" description="Edit the event subscription's properties as raw JSON. This overrides the other tabs when non-empty.">
      <Textarea rows={16} style={{ fontFamily: "monospace", width: "100%" }} value={f.advancedJson}
        placeholder={JSON.stringify(api.toSubscriptionBody(f).properties, null, 2)}
        onChange={set("advancedJson")} aria-label="Advanced editor JSON" />
    </FormSection>
  );

  const body = () => {
    if (f.advancedJson.trim()) {
      try { return { properties: JSON.parse(f.advancedJson) }; } catch { /* fall through to the composed body */ }
    }
    return api.toSubscriptionBody(f);
  };

  const review = () => {
    const b = body(), p = b.properties;
    const dl = (rows) => <dl>{rows.map(([k, v]) => [<dt key={k + "t"}>{k}</dt>, <dd key={k + "d"}>{v}</dd>])}</dl>;
    return (
      <>
        <h3>Basic</h3>
        {dl([["Name", f.name || "--"], ["Event Schema", f.eventSchema], ["Endpoint Type", f.endpointType], ["Endpoint", f.endpoint || "--"]])}
        <h3>Filters</h3>
        {dl([["Subject filter", f.subjectFilter ? `${f.subjectBeginsWith || "*"} .. ${f.subjectEndsWith || "*"}` : "None"], ["Advanced filters", String(p.filter?.advancedFilters?.length || 0)]])}
        <h3>Additional Features</h3>
        {dl([["Dead-lettering", f.deadLetter ? "Enabled" : "Disabled"], ["Max delivery attempts", String(f.maxDeliveryAttempts)], ["Event TTL (minutes)", String(f.eventTtl)]])}
      </>
    );
  };

  const onCreate = async () => {
    try {
      await api.createEventSubscription(rg, topic, f.name, body());
      notify.success(`Event subscription '${f.name}' was created.`, "Deployment succeeded");
      navigate("eventgrid", "topics", rg, topic, "eventsubscriptions");
    } catch (e) { notify.error(e, "Deployment failed"); }
  };

  return (
    <CreateWizard
      title="Create Event Subscription" closeHref={`#/eventgrid/topics/${encodeURIComponent(rg)}/${encodeURIComponent(topic)}`} glyph={<Glyph id="eventgrid" />}
      tabs={[
        { id: "basic", label: "Basic", content: basic, validate: basicsErrors },
        { id: "filters", label: "Filters", content: filters },
        { id: "additional", label: "Additional Features", content: additional },
        { id: "delivery", label: "Delivery Properties", content: delivery },
        { id: "advanced", label: "Advanced Editor", content: advancedEditor },
      ]}
      review={review}
      onCreate={onCreate}
    />
  );
}
