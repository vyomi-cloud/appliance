import { useState } from "react";
import { Button, Checkbox, MessageBar, MessageBarBody } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { getPrefs, setPrefs } from "./prefs.js";

export default function PreviewFeatures() {
  const [prefs, setLocal] = useState(getPrefs());
  const [saved, setSaved] = useState(false);
  const toggle = (k) => setLocal((p) => ({ ...p, [k]: !p[k] }));

  return (
    <CostShell active="previewfeatures">
      <div className="vy-page">
        {saved && <MessageBar intent="success"><MessageBarBody>Preview features applied. Vyomi stores this setting in your browser and does not enforce it server-side.</MessageBarBody></MessageBar>}
        <section className="vy-form-section">
          <h3>Preview features</h3>
          <div><Checkbox label="Charts in the cost analysis preview" checked={prefs.chartsPreview} onChange={() => toggle("chartsPreview")} /></div>
          <div><Checkbox label="Forecast in the cost analysis preview" checked={prefs.forecastPreview} onChange={() => toggle("forecastPreview")} /></div>
          <div><Checkbox label="Change scope from menu" checked={prefs.changeScopeFromMenu} onChange={() => toggle("changeScopeFromMenu")} /></div>
          <div style={{ marginTop: 16 }}>
            <Button appearance="primary" onClick={() => { setPrefs(prefs); setSaved(true); setTimeout(() => location.reload(), 600); }}>Apply + reload</Button>{" "}
            <Button onClick={() => { location.hash = "#/cost/overview"; }}>Cancel</Button>
          </div>
        </section>
      </div>
    </CostShell>
  );
}
