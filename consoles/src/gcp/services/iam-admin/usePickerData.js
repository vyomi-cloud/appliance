/* Shared data for the pickers: catalog roles + permissions (catalog.js), custom roles, and principals from the stores
 * (service accounts, groups, members already on the project policy). Each source degrades independently. */
import { useEffect, useState } from "react";
import { useIamApi } from "../../../common/iamEnforceHooks.js";
import { fromCustomRole, loadCatalog, CATALOG_SERVICES } from "./catalog.js";
import * as api from "./api.js";

export function usePickerData({ withPrincipals = false } = {}) {
  const iam = useIamApi("gcp");
  const [s, set] = useState({ loading: true, roles: [], permissions: [], principals: [], services: CATALOG_SERVICES, error: null });
  useEffect(() => {
    let on = true;
    (async () => {
      const [cat, custom, sas, groups, pol] = await Promise.all([
        loadCatalog(iam).catch((e) => ({ error: e })),
        api.listCustomRoles().catch(() => []),
        withPrincipals ? api.listServiceAccounts().catch(() => []) : [],
        withPrincipals ? api.listGroups().catch(() => []) : [],
        withPrincipals ? api.getIamPolicy().catch(() => null) : null,
      ]);
      const principals = new Map();
      const add = (member, group, name) => { if (!principals.has(member)) principals.set(member, { member, group, name }); };
      for (const a of sas) add(`serviceAccount:${a.email}`, "Service accounts", a.displayName || a.email);
      for (const g of groups) if (g.groupKey?.id) add(`group:${g.groupKey.id}`, "Groups", g.displayName || g.groupKey.id);
      for (const b of pol?.bindings || []) for (const m of b.members) { const i = api.parseMember(m); add(m, i.type === "Service account" ? "Service accounts" : i.type === "Group" ? "Groups" : "Users and others", i.display.split("@")[0]); }
      if (on) set({ loading: false, roles: [...(cat.roles || []), ...custom.map(fromCustomRole)], permissions: cat.permissions || [], principals: [...principals.values()], services: CATALOG_SERVICES, error: cat.error || null });
    })();
    return () => { on = false; };
  }, [iam, withPrincipals]);
  return s;
}
