/* Shared "Compute + storage" field set: service/compute tier, vCore auto-scaling, auto-pause
 * delay, max size, zone redundancy and the cost summary. Rendered by ConfigureDatabaseDialog
 * (the create-wizard / "Configure database" modal) AND the database's standalone Compute +
 * storage settings panel, so both stay in lockstep. */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Radio, RadioGroup, Select } from "@fluentui/react-components";
import { NotSimulated } from "../../kit/common.jsx";
import { SERVICE_TIERS, estimateMonthlyCost } from "./api.js";

const VCORE_OPTIONS = [0.5, 1, 2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 80];

export const DEFAULT_COMPUTE_STORAGE = {
  tier: "GeneralPurpose", serverless: true, maxVCores: 2, minVCores: 0.5,
  autoPause: true, days: 0, hours: 1, minutes: 0, dataMaxSizeGb: 32, zoneRedundant: false,
};

export default function ComputeStorageFields({ f, set }) {
  const [hw, setHw] = useState(false);
  const tier = SERVICE_TIERS.find((t) => t.value === f.tier) || SERVICE_TIERS[0];
  const cost = tier.vcore ? estimateMonthlyCost(f) : null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section className="vy-section">
        <h3>Service and compute tier</h3>
        <Field label="Service tier">
          <Select value={f.tier} onChange={(_, d) => set("tier")(d.value)} aria-label="Service tier">
            {SERVICE_TIERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </Select>
        </Field>
        {tier.vcore && (
          <Field label="Compute tier" style={{ marginTop: 8 }}>
            <RadioGroup layout="horizontal" value={f.serverless ? "Serverless" : "Provisioned"} onChange={(_, d) => set("serverless")(d.value === "Serverless")} aria-label="Compute tier" disabled={!tier.serverless}>
              <Radio value="Provisioned" label="Provisioned" />
              <Radio value="Serverless" label="Serverless" disabled={!tier.serverless} />
            </RadioGroup>
          </Field>
        )}
      </section>

      <section className="vy-section">
        <h3>Compute Hardware</h3>
        <Field label="Hardware configuration">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Input readOnly value="Standard-series (Gen5)" aria-label="Hardware configuration" />
            <Button onClick={() => setHw(true)}>Change configuration</Button>
          </div>
        </Field>
      </section>

      {tier.vcore && (
        <section className="vy-section">
          <h3>{f.serverless ? "Auto-scaling" : "vCores"}</h3>
          <Field label="Max vCores">
            <Select value={String(f.maxVCores)} onChange={(_, d) => set("maxVCores")(Number(d.value))} aria-label="Max vCores">
              {VCORE_OPTIONS.map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          </Field>
          {f.serverless && (
            <Field label="Min vCores" style={{ marginTop: 8 }}>
              <Select value={String(f.minVCores)} onChange={(_, d) => set("minVCores")(Number(d.value))} aria-label="Min vCores">
                {VCORE_OPTIONS.filter((v) => v <= f.maxVCores).map((v) => <option key={v} value={v}>{v}</option>)}
              </Select>
            </Field>
          )}
        </section>
      )}

      {tier.vcore && f.serverless && (
        <section className="vy-section">
          <h3>Auto-pause delay</h3>
          <Checkbox label="Enable auto-pause" checked={f.autoPause} onChange={(_, d) => set("autoPause")(!!d.checked)} />
          {f.autoPause && (
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <Field label="Days"><Input type="number" min={0} value={String(f.days)} onChange={(_, d) => set("days")(Number(d.value) || 0)} aria-label="Days" style={{ width: 80 }} /></Field>
              <Field label="Hours"><Input type="number" min={0} max={23} value={String(f.hours)} onChange={(_, d) => set("hours")(Number(d.value) || 0)} aria-label="Hours" style={{ width: 80 }} /></Field>
              <Field label="Minutes"><Input type="number" min={0} max={59} value={String(f.minutes)} onChange={(_, d) => set("minutes")(Number(d.value) || 0)} aria-label="Minutes" style={{ width: 80 }} /></Field>
            </div>
          )}
        </section>
      )}

      <section className="vy-section">
        <h3>Data max size</h3>
        <Field label="Data max size (GB)">
          <Input type="number" min={1} value={String(f.dataMaxSizeGb)} onChange={(_, d) => set("dataMaxSizeGb")(Number(d.value) || 1)} aria-label="Data max size (GB)" />
        </Field>
      </section>

      {tier.vcore && (
        <section className="vy-section">
          <h3>Zone redundancy</h3>
          <Field label="Would you like to make this database zone redundant?">
            <RadioGroup layout="horizontal" value={f.zoneRedundant ? "Yes" : "No"} onChange={(_, d) => set("zoneRedundant")(d.value === "Yes")} aria-label="Would you like to make this database zone redundant?">
              <Radio value="Yes" label="Yes" /><Radio value="No" label="No" />
            </RadioGroup>
          </Field>
        </section>
      )}

      <section className="vy-section">
        <h3>Cost summary</h3>
        {cost !== null
          ? <p style={{ fontSize: 13 }}>Estimated cost: <b>${cost.toFixed(2)}/month</b> ({f.serverless ? "serverless, averaged between min/max vCores" : "provisioned"}).</p>
          : <p style={{ fontSize: 13 }}>Estimated cost is based on the selected DTU performance level.</p>}
      </section>

      <Dialog open={hw} onOpenChange={(_, d) => !d.open && setHw(false)}>
        <DialogSurface aria-label="Change configuration">
          <DialogBody>
            <DialogTitle>Change configuration</DialogTitle>
            <DialogContent><NotSimulated feature="Hardware generation selection (M-series, Fsv2-series, DC-series)" /></DialogContent>
            <DialogActions><Button onClick={() => setHw(false)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
