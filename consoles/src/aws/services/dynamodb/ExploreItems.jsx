/* Explore items: scan or query a table (or one of its GSIs), create/edit items as JSON, delete items. */
import { useEffect, useMemo, useState } from "react";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import Textarea from "@cloudscape-design/components/textarea";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Multiselect from "@cloudscape-design/components/multiselect";
import Container from "@cloudscape-design/components/container";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import Grid from "@cloudscape-design/components/grid";
import Input from "@cloudscape-design/components/input";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Alert from "@cloudscape-design/components/alert";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { keyOf } from "./Tables.jsx";
import { getExploreSettings } from "./prefs.js";
import * as api from "./api.js";

const ATTR_TYPES = ["String", "Number", "Boolean", "Null", "JSON"];

function fieldsFromObj(obj) {
  return Object.entries(obj || {}).map(([key, value]) => {
    if (typeof value === "number") return { key, type: "Number", value: String(value) };
    if (typeof value === "boolean") return { key, type: "Boolean", value: String(value) };
    if (value === null) return { key, type: "Null", value: "" };
    if (typeof value === "object") return { key, type: "JSON", value: JSON.stringify(value) };
    return { key, type: "String", value: String(value ?? "") };
  });
}
function objFromFields(fields) {
  const obj = {};
  for (const f of fields) {
    if (!f.key) continue;
    if (f.type === "Number") obj[f.key] = Number(f.value) || 0;
    else if (f.type === "Boolean") obj[f.key] = f.value === "true";
    else if (f.type === "Null") obj[f.key] = null;
    else if (f.type === "JSON") { try { obj[f.key] = JSON.parse(f.value); } catch { obj[f.key] = f.value; } }
    else obj[f.key] = f.value;
  }
  return obj;
}
const jsonTextFor = (obj, syntax) => JSON.stringify(syntax === "DynamoDB JSON" ? api.marshalItem(obj) : obj, null, 2);
const objFromJsonText = (text, syntax) => { const parsed = JSON.parse(text); return syntax === "DynamoDB JSON" ? api.unmarshalItem(parsed) : parsed; };

const OPERATORS = [{ value: "eq", label: "=" }, { value: "ne", label: "≠" }, { value: "contains", label: "contains" }, { value: "begins", label: "begins with" }];
const PROJECTION_OPTIONS = [{ value: "ALL", label: "All attributes" }, { value: "SPECIFIC", label: "Specific attributes" }];
const applyOp = (v, op, needle) => {
  const a = v === undefined || v === null ? "" : String(v);
  switch (op) {
    case "eq": return a === needle;
    case "ne": return a !== needle;
    case "contains": return a.includes(needle);
    case "begins": return a.startsWith(needle);
    default: return true;
  }
};

export default function ExploreItems({ params }) {
  const name = params.name;
  const notify = useNotify();
  const settings = getExploreSettings();
  const [sel, setSel] = useState([]);
  const [edit, setEdit] = useState(null);      // {isNew, viewMode, jsonSyntax, fields, json}
  const [editErr, setEditErr] = useState(null);
  const [del, setDel] = useState(false);
  const meta = useAsync(() => api.describeTable(name), [name]);

  const openEdit = (obj, isNew) => {
    const viewMode = settings.defaultItemEditorView === "JSON view" ? "json" : "form";
    setEdit({ isNew, viewMode, jsonSyntax: settings.defaultJsonSyntax, fields: fieldsFromObj(obj), json: jsonTextFor(obj, settings.defaultJsonSyntax) });
    setEditErr(null);
  };
  const setViewMode = (viewMode) => {
    setEdit((e) => {
      if (viewMode === "json") return { ...e, viewMode, json: jsonTextFor(objFromFields(e.fields), e.jsonSyntax) };
      try { return { ...e, viewMode, fields: fieldsFromObj(objFromJsonText(e.json, e.jsonSyntax)) }; }
      catch (err) { setEditErr(err); return e; }
    });
  };
  const setJsonSyntax = (jsonSyntax) => {
    setEdit((e) => {
      try { return { ...e, jsonSyntax, json: jsonTextFor(objFromJsonText(e.json, e.jsonSyntax), jsonSyntax) }; }
      catch (err) { setEditErr(err); return { ...e, jsonSyntax }; }
    });
  };

  const [op, setOp] = useState(settings.defaultQueryType === "Query" ? "query" : "scan");
  const [indexSel, setIndexSel] = useState("TABLE");
  const [pkVal, setPkVal] = useState(""); const [skVal, setSkVal] = useState("");
  const [projection, setProjection] = useState("ALL");
  const [projAttrs, setProjAttrs] = useState([]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState([]);
  const [result, setResult] = useState({ items: [], scannedCount: 0, loading: true, error: null });

  const indexOptions = useMemo(() => [
    { value: "TABLE", label: `Table - ${name}` },
    ...(meta.data?.GlobalSecondaryIndexes || []).map((g) => ({ value: g.IndexName, label: `Index - ${g.IndexName}` })),
  ], [meta.data, name]);
  const activeKeys = useMemo(() => {
    if (indexSel === "TABLE" || !meta.data) return { pk: keyOf(meta.data || {}, "HASH"), sk: keyOf(meta.data || {}, "RANGE") };
    const gsi = meta.data.GlobalSecondaryIndexes?.find((g) => g.IndexName === indexSel);
    return { pk: gsi?.KeySchema?.find((k) => k.KeyType === "HASH")?.AttributeName, sk: gsi?.KeySchema?.find((k) => k.KeyType === "RANGE")?.AttributeName };
  }, [meta.data, indexSel]);
  const attrType = (attrName) => meta.data?.AttributeDefinitions?.find((a) => a.AttributeName === attrName)?.AttributeType || "S";
  const marshalKey = (attrName, value) => (attrType(attrName) === "N" ? { N: String(Number(value) || 0) } : { S: String(value) });

  const keyAttrs = [keyOf(meta.data || {}, "HASH"), keyOf(meta.data || {}, "RANGE")].filter(Boolean);
  const keyFor = (it) => Object.fromEntries(keyAttrs.map((k) => [k, it[k]]));

  const run = async () => {
    setResult((r) => ({ ...r, loading: true, error: null }));
    try {
      let data;
      if (op === "query" && activeKeys.pk) {
        const expr = activeKeys.sk && skVal ? `${activeKeys.pk} = :pk AND ${activeKeys.sk} = :sk` : `${activeKeys.pk} = :pk`;
        data = await api.query({
          TableName: name,
          ...(indexSel !== "TABLE" ? { IndexName: indexSel } : {}),
          KeyConditionExpression: expr,
          ExpressionAttributeValues: { ":pk": marshalKey(activeKeys.pk, pkVal), ...(activeKeys.sk && skVal ? { ":sk": marshalKey(activeKeys.sk, skVal) } : {}) },
        });
      } else {
        data = await api.scan(name, { limit: 50 });
      }
      setResult({ items: data.Items || [], scannedCount: data.ScannedCount ?? (data.Items || []).length, loading: false, error: null });
    } catch (e) { setResult((r) => ({ ...r, loading: false, error: e })); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, [name]);

  const rawItems = result.items;
  const items = useMemo(() => rawItems.filter((it) =>
    filters.every((f) => !f.attr || applyOp(api.unmarshal(it[f.attr]), f.op, f.value))), [rawItems, filters]);

  const attrs = useMemo(() => {
    const keys = [keyOf(meta.data || {}, "HASH"), keyOf(meta.data || {}, "RANGE")].filter(Boolean);
    const rest = new Set();
    rawItems.forEach((it) => Object.keys(it).forEach((k) => !keys.includes(k) && rest.add(k)));
    const all = [...keys, ...[...rest].sort()];
    if (projection !== "SPECIFIC" || !projAttrs.length) return all;
    const chosen = new Set(projAttrs.map((o) => o.value));
    return all.filter((a) => keys.includes(a) || chosen.has(a));
  }, [rawItems, meta.data, projection, projAttrs]);
  const attrOptions = useMemo(() => {
    const keys = [keyOf(meta.data || {}, "HASH"), keyOf(meta.data || {}, "RANGE")].filter(Boolean);
    const rest = new Set();
    rawItems.forEach((it) => Object.keys(it).forEach((k) => !keys.includes(k) && rest.add(k)));
    return [...keys, ...[...rest].sort()].map((a) => ({ value: a, label: a }));
  }, [rawItems, meta.data]);

  const save = async () => {
    setEditErr(null);
    try {
      const obj = edit.viewMode === "json" ? objFromJsonText(edit.json, edit.jsonSyntax) : objFromFields(edit.fields);
      await api.putItem(name, api.marshalItem(obj));
      notify.success(edit.isNew ? "The item has been saved successfully." : "The item has been updated successfully.");
      setEdit(null); run();
    } catch (e) { setEditErr(e); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Explore items: {name}</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" description="Scan or query a table or index.">Scan or query items</Header>}>
          <SpaceBetween size="l">
            <FormField label="Operation">
              <RadioGroup value={op} onChange={({ detail }) => setOp(detail.value)} items={[{ value: "scan", label: "Scan" }, { value: "query", label: "Query" }]} />
            </FormField>
            <Grid gridDefinition={op === "query" ? [{ colspan: 4 }, { colspan: 4 }, { colspan: 4 }] : [{ colspan: 6 }, { colspan: 6 }]}>
              <FormField label="Select a table or index">
                <Select selectedOption={indexOptions.find((o) => o.value === indexSel) || indexOptions[0]} options={indexOptions}
                  onChange={({ detail }) => setIndexSel(detail.selectedOption.value)} ariaLabel="Select a table or index" />
              </FormField>
              <FormField label="Select attribute projection">
                <Select selectedOption={PROJECTION_OPTIONS.find((o) => o.value === projection)}
                  options={PROJECTION_OPTIONS}
                  onChange={({ detail }) => setProjection(detail.selectedOption.value)} ariaLabel="Select attribute projection" />
              </FormField>
              {op === "query" && (
                <FormField label={`Partition key: ${activeKeys.pk || "-"}`}>
                  <Input value={pkVal} onChange={({ detail }) => setPkVal(detail.value)} placeholder="Enter a value" ariaLabel="Partition key value" />
                </FormField>
              )}
            </Grid>
            {projection === "SPECIFIC" && (
              <FormField label="Attributes to show">
                <Multiselect selectedOptions={projAttrs} onChange={({ detail }) => setProjAttrs(detail.selectedOptions)} options={attrOptions} placeholder="Choose attributes" />
              </FormField>
            )}
            {op === "query" && activeKeys.sk && (
              <FormField label={`Sort key: ${activeKeys.sk} - optional`}>
                <Input value={skVal} onChange={({ detail }) => setSkVal(detail.value)} placeholder="Enter a value" ariaLabel="Sort key value" />
              </FormField>
            )}
            <ExpandableSection headerText="Filters - optional" expanded={filtersOpen} onChange={({ detail }) => setFiltersOpen(detail.expanded)}>
              <SpaceBetween size="xs">
                {filters.map((f, i) => (
                  <Grid key={i} gridDefinition={[{ colspan: 4 }, { colspan: 3 }, { colspan: 4 }, { colspan: 1 }]}>
                    <Select selectedOption={attrOptions.find((o) => o.value === f.attr) || null} options={attrOptions} placeholder="Attribute"
                      onChange={({ detail }) => setFilters(filters.map((x, j) => (j === i ? { ...x, attr: detail.selectedOption.value } : x)))} />
                    <Select selectedOption={OPERATORS.find((o) => o.value === f.op)} options={OPERATORS}
                      onChange={({ detail }) => setFilters(filters.map((x, j) => (j === i ? { ...x, op: detail.selectedOption.value } : x)))} />
                    <Input value={f.value} placeholder="Value" onChange={({ detail }) => setFilters(filters.map((x, j) => (j === i ? { ...x, value: detail.value } : x)))} />
                    <Button iconName="close" variant="icon" onClick={() => setFilters(filters.filter((_, j) => j !== i))} ariaLabel="Remove filter" />
                  </Grid>
                ))}
                <Button onClick={() => setFilters([...filters, { attr: "", op: "eq", value: "" }])}>Add filter</Button>
              </SpaceBetween>
            </ExpandableSection>
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="primary" onClick={run} loading={result.loading}>Run</Button>
              <Button onClick={() => { setOp("scan"); setIndexSel("TABLE"); setPkVal(""); setSkVal(""); setProjection("ALL"); setProjAttrs([]); setFilters([]); setFiltersOpen(false); run(); }}>Reset</Button>
            </SpaceBetween>
          </SpaceBetween>
        </Container>
        {!result.error && <Alert type="success" statusIconAriaLabel="Success">
          Completed · Items returned: {items.length} · Items scanned: {result.scannedCount}
        </Alert>}
        <Table
          variant="container"
          items={items}
          loading={result.loading}
          selectionType="multi"
          selectedItems={sel}
          onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          trackBy={(it) => JSON.stringify(keyFor(it))}
          header={<Header variant="h2" counter={`(${items.length})`} actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button disabled={sel.length !== 1} onClick={() => openEdit(api.unmarshalItem(sel[0]), false)}>Edit item</Button>
              <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete items</Button>
              <Button variant="primary" onClick={() => openEdit(Object.fromEntries(keyAttrs.map((k) => [k, ""])), true)}>Create item</Button>
            </SpaceBetween>
          }>Table: {name} - Items returned</Header>}
          columnDefinitions={attrs.map((a) => ({ id: a, header: keyAttrs.includes(a) ? `${a} (${keyAttrs[0] === a ? "Partition key" : "Sort key"})` : a, cell: (it) => it[a] === undefined ? "" : fmt(api.unmarshal(it[a])) }))}
          empty={<Box textAlign="center" color="inherit"><b>The query did not return any results.</b></Box>}
        />
        {result.error && <ErrorAlert error={result.error} />}
      </SpaceBetween>
      <Modal visible={!!edit} size="large" onDismiss={() => setEdit(null)} header={edit?.isNew ? "Create item" : "Edit item"}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save}>{edit?.isNew ? "Create item" : "Save changes"}</Button></SpaceBetween></Box>}>
        {edit && (
          <SpaceBetween size="l">
            <FormField label="Item editor view">
              <RadioGroup value={edit.viewMode} onChange={({ detail }) => setViewMode(detail.value)}
                items={[{ value: "form", label: "Form view" }, { value: "json", label: "JSON view" }]} />
            </FormField>
            {edit.viewMode === "json" ? (
              <>
                <FormField label="View as">
                  <RadioGroup value={edit.jsonSyntax} onChange={({ detail }) => setJsonSyntax(detail.value)}
                    items={[{ value: "DynamoDB JSON", label: "DynamoDB JSON" }, { value: "JSON", label: "JSON" }]} />
                </FormField>
                <FormField label="Attributes" description="Strings, numbers, booleans, null, lists and maps are converted to DynamoDB types." errorText={editErr?.message}>
                  <Textarea rows={14} value={edit.json} onChange={({ detail }) => setEdit({ ...edit, json: detail.value })} />
                </FormField>
              </>
            ) : (
              <FormField label="Attributes" errorText={editErr?.message}>
                <SpaceBetween size="xs">
                  {edit.fields.map((f, i) => (
                    <Grid key={i} gridDefinition={[{ colspan: 4 }, { colspan: 3 }, { colspan: 4 }, { colspan: 1 }]}>
                      <Input value={f.key} placeholder="Attribute name" disabled={keyAttrs.includes(f.key)}
                        onChange={({ detail }) => setEdit({ ...edit, fields: edit.fields.map((x, j) => (j === i ? { ...x, key: detail.value } : x)) })} />
                      <Select selectedOption={{ value: f.type, label: f.type }} options={ATTR_TYPES.map((t) => ({ value: t, label: t }))}
                        onChange={({ detail }) => setEdit({ ...edit, fields: edit.fields.map((x, j) => (j === i ? { ...x, type: detail.selectedOption.value } : x)) })} />
                      <Input value={f.value} placeholder="Value" disabled={f.type === "Null"}
                        onChange={({ detail }) => setEdit({ ...edit, fields: edit.fields.map((x, j) => (j === i ? { ...x, value: detail.value } : x)) })} />
                      <Button iconName="close" variant="icon" ariaLabel="Remove attribute" disabled={keyAttrs.includes(f.key)}
                        onClick={() => setEdit({ ...edit, fields: edit.fields.filter((_, j) => j !== i) })} />
                    </Grid>
                  ))}
                  <Button onClick={() => setEdit({ ...edit, fields: [...edit.fields, { key: "", type: "String", value: "" }] })}>Add new attribute</Button>
                </SpaceBetween>
              </FormField>
            )}
          </SpaceBetween>
        )}
      </Modal>
      <DeleteModal visible={del} resourceType="item" names={sel.map((it) => JSON.stringify(api.unmarshalItem(keyFor(it))))} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const it of sel) await api.deleteItem(name, keyFor(it)); notify.success(`${sel.length} item(s) deleted.`); setSel([]); run(); }} />
    </ContentLayout>
  );
}

const fmt = (v) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));
