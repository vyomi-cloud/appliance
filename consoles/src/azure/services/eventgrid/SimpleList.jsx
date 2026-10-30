/* A real browse blade for Event Grid's sibling resource types (Namespaces, System topics,
 * Domains, Partner configurations, Partner topics, Partner registrations, Partner namespaces)
 * — the same generic ARM catalog CRUD Topics.jsx uses, over a different (namespace, type).
 * No capture-backed table/create spec exists for these (out of Vyomi's detail-blade scope for
 * this release), so the list is a minimal real one: Name/Resource group/Location/Status plus a
 * quick "Create" dialog (name only) and Delete — enough for every element to be real, not a
 * disabled skeleton. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input,
} from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { DEFAULT_RG, locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export default function SimpleList({ typeKey, title, resourceLabel, defaultName, closeHref }) {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listSibling(typeKey), [typeKey, sub.id]);
  const subName = sub.displayName || sub.id;
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState(defaultName);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      await api.createSibling(typeKey, DEFAULT_RG, name, { location: "eastus" });
      notify.success(`'${name}' was created.`, "Create succeeded");
      setCreating(false);
      reload();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };

  return (
    <>
      <TitleRow title={title} glyph={<Glyph id="eventgrid" />} closeHref={closeHref} />
      <div className="vy-page">
        <BrowseGrid
          resourceName={resourceLabel}
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => { setName(defaultName); setCreating(true); }}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteSibling(typeKey, r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} ${rows.length === 1 ? resourceLabel : `${resourceLabel}s`}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName={`${typeKey}.csv`}
          columns={[
            { key: "name", label: "Name" },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState, hidden: true },
          ]}
        />
      </div>
      <Dialog open={creating} onOpenChange={(_, d) => setCreating(d.open)}>
        <DialogSurface aria-label={`Create ${resourceLabel}`}>
          <DialogBody>
            <DialogTitle>Create {resourceLabel}</DialogTitle>
            <DialogContent>
              <Field label="Name" required>
                <Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" autoFocus />
              </Field>
              <Field label="Resource group"><Input readOnly value={DEFAULT_RG} aria-label="Resource group" /></Field>
              <Field label="Region"><Input readOnly value="East US" aria-label="Region" /></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!name.trim() || busy} onClick={create}>Create</Button>
              <Button onClick={() => setCreating(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
