/* Reusable AWS permission pickers, all fed from the verbatim IAM catalogs (GET /api/iam/aws/catalog/<svc>; in the browser on Nano).
 *   <ServicePicker/>      "Choose a service": Commonly used services, then Other services, searchable.
 *   <ActionPicker/>       actions of one service from the catalog (single or multi), grouped by access level.
 *   <ResourceArnPicker/>  resource type from the catalog + ARN entry prefilled with the catalog ARN format.
 *   <PermissionPicker/>   service + action together (Policy simulator, Effective access).
 *   <PrincipalPicker/>    searchable user/role selector fed by the IAM list APIs.
 *   useCatalog / useCatalogs hooks share one in-memory cache. */
import { useEffect, useMemo, useState } from "react";
import Select from "@cloudscape-design/components/select";
import Multiselect from "@cloudscape-design/components/multiselect";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import { useIamApi } from "../../common/iamEnforceHooks.js";
import { IAM_SERVICES, COMMON_PREFIXES } from "./iamServices.js";
import { LEVELS, actionNames, resourceTypesFor, arnTemplate } from "./iamPolicy.js";
import * as iamApi from "../services/iam/api.js";

const cache = new Map(); // service -> Promise<catalog|null>
export const loadCatalog = (api, svc) => {
  if (!svc) return Promise.resolve(null);
  if (!cache.has(svc)) cache.set(svc, api.catalog(svc).catch(() => null));
  return cache.get(svc);
};

export function useCatalog(service) {
  const api = useIamApi("aws");
  const [st, setSt] = useState({ service: null, cat: null });
  useEffect(() => {
    let live = true;
    if (!service) { setSt({ service: null, cat: null }); return undefined; }
    loadCatalog(api, service).then((c) => live && setSt({ service, cat: c }));
    return () => { live = false; };
  }, [api, service]);
  const loading = !!service && st.service !== service;
  return { cat: loading ? null : st.cat, loading, missing: !!service && !loading && !st.cat };
}

/** Load several catalogs at once: returns {prefix: catalog}; `ready` is false until every one resolved. */
export function useCatalogs(prefixes) {
  const api = useIamApi("aws");
  const key = [...new Set(prefixes)].sort().join(",");
  const [cats, setCats] = useState({});
  useEffect(() => {
    let live = true;
    const list = key ? key.split(",") : [];
    Promise.all(list.map((p) => loadCatalog(api, p).then((c) => [p, c]))).then((rows) => live && setCats(Object.fromEntries(rows.filter(([, c]) => c))));
    return () => { live = false; };
  }, [api, key]);
  return cats;
}

const svcOption = ([value, label]) => ({ value, label });
export const serviceLabel = (prefix) => (IAM_SERVICES.find(([p]) => p === prefix) || [])[1] || prefix;

export function ServicePicker({ value, onChange, ariaLabel = "Service", placeholder = "Choose a service", services, invalid, disabled }) {
  const all = services || IAM_SERVICES;
  const common = all.filter(([p]) => COMMON_PREFIXES.includes(p));
  const options = [
    ...(common.length ? [{ label: "Commonly used services", options: common.map(svcOption) }] : []),
    { label: common.length ? "Other services" : "Services", options: all.filter(([p]) => !COMMON_PREFIXES.includes(p) || !common.length).map(svcOption) },
  ];
  const flat = options.flatMap((g) => g.options);
  return (
    <Select ariaLabel={ariaLabel} placeholder={placeholder} filteringType="auto" filteringPlaceholder="Search services" filteringAriaLabel="Search services" empty="No matching services"
      invalid={invalid} disabled={disabled}
      selectedOption={flat.find((o) => o.value === value) || null} options={options}
      onChange={({ detail }) => onChange(detail.selectedOption.value)} />
  );
}

const actionOptions = (cat, service) => LEVELS.map(([lv, label]) => ({
  label, options: actionNames(cat).filter((n) => cat.actions[n].l === lv).sort().map((n) => ({ value: n, label: n, description: `${service}:${n}` })),
})).filter((g) => g.options.length);

/** multiple=false: value is a name or "" (Select); multiple=true: value is an array of names (Multiselect). */
export function ActionPicker({ service, value, onChange, multiple = false, ariaLabel = "Action", placeholder }) {
  const { cat, loading } = useCatalog(service);
  const groups = useMemo(() => (cat ? actionOptions(cat, service) : []), [cat, service]);
  const flat = groups.flatMap((g) => g.options);
  if (multiple) {
    return <Multiselect ariaLabel={ariaLabel} filteringType="auto" keepOpen statusType={loading ? "loading" : "finished"} loadingText="Loading actions" disabled={!service}
      placeholder={placeholder || (service ? "Choose actions" : "Choose a service first")} options={groups} selectedOptions={flat.filter((o) => (value || []).includes(o.value))}
      onChange={({ detail }) => onChange(detail.selectedOptions.map((o) => o.value))} deselectAriaLabel={(o) => `Remove ${o.label}`} />;
  }
  return <Select ariaLabel={ariaLabel} filteringType="auto" filteringPlaceholder="Filter actions" statusType={loading ? "loading" : "finished"} loadingText="Loading actions" disabled={!service}
    placeholder={placeholder || (service ? "Choose an action" : "Choose a service first")} options={groups} selectedOption={flat.find((o) => o.value === value) || null}
    onChange={({ detail }) => onChange(detail.selectedOption.value)} />;
}

/** Resource type from the catalog (restricted to `action` when given) + ARN input prefilled with the catalog ARN format. value = the ARN. */
export function ResourceArnPicker({ service, action, value, onChange, ariaLabel = "Resource ARN" }) {
  const { cat } = useCatalog(service);
  const [type, setType] = useState("");
  const types = cat ? resourceTypesFor(cat, action ? [action] : actionNames(cat)).filter((t) => t !== "*") : [];
  const options = [{ value: "*", label: "All resources (*)" }, ...types.map((t) => ({ value: t, label: t, description: arnTemplate(cat, t) }))];
  const pick = (t) => { setType(t); onChange(t === "*" ? "*" : arnTemplate(cat, t).replace(/\$\{Partition\}/g, "aws").replace(/\$\{Account\}/g, "123456789012").replace(/\$\{Region\}/g, "us-east-1")); };
  return (
    <SpaceBetween size="xs">
      <Select ariaLabel="Resource type" placeholder={service ? "Choose a resource type" : "Choose a service first"} disabled={!cat} options={options}
        selectedOption={options.find((o) => o.value === type) || null} onChange={({ detail }) => pick(detail.selectedOption.value)} />
      <Input ariaLabel={ariaLabel} value={value} onChange={({ detail }) => onChange(detail.value)} placeholder="arn:aws:s3:::my-bucket/*" />
      {type && type !== "*" && <Box variant="small" color="text-body-secondary">ARN format: {arnTemplate(cat, type)}</Box>}
    </SpaceBetween>
  );
}

export function PermissionPicker({ service, action, onChange, serviceLabelText = "Service", actionLabelText = "Action", actionDescription }) {
  return (
    <SpaceBetween size="m">
      <FormField label={serviceLabelText}><ServicePicker value={service} onChange={(s) => onChange({ service: s, action: "" })} /></FormField>
      <FormField label={actionLabelText} description={actionDescription}><ActionPicker service={service} value={action} onChange={(a) => onChange({ service, action: a })} /></FormField>
    </SpaceBetween>
  );
}

/** Searchable user/role selector from ListUsers + ListRoles. value = ARN. */
export function PrincipalPicker({ value, onChange, ariaLabel = "Principal" }) {
  const [opts, setOpts] = useState(null);
  useEffect(() => {
    let live = true;
    Promise.all([iamApi.listUsers().catch(() => []), iamApi.listRoles().catch(() => [])]).then(([u, r]) => live && setOpts([
      { label: "Users", options: u.map((x) => ({ value: x.Arn, label: x.UserName, description: x.Arn })) },
      { label: "Roles", options: r.map((x) => ({ value: x.Arn, label: x.RoleName, description: x.Arn })) },
    ].filter((g) => g.options.length)));
    return () => { live = false; };
  }, []);
  const flat = (opts || []).flatMap((g) => g.options);
  return <Select ariaLabel={ariaLabel} filteringType="auto" filteringPlaceholder="Search users and roles" statusType={opts ? "finished" : "loading"} empty="No users or roles"
    placeholder="Choose a user or role" options={opts || []} selectedOption={flat.find((o) => o.value === value) || null} onChange={({ detail }) => onChange(detail.selectedOption.value)} />;
}
