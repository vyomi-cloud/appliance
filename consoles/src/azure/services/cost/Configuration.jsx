import { useState } from "react";
import { Button, Select } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { getPrefs, setPrefs } from "./prefs.js";

export default function Configuration() {
  const [currency, setCurrency] = useState(getPrefs().defaultCurrency);
  const [saved, setSaved] = useState(false);

  return (
    <CostShell active="configuration">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>Configuration</h3>
          <div className="vy-form-row"><label>Default currency</label><div>
            <Select value={currency} onChange={(_, d) => setCurrency(d.value)} aria-label="Default currency">
              <option value="USD">USD</option>
            </Select>
          </div></div>
          <Button appearance="primary" onClick={() => { setPrefs({ ...getPrefs(), defaultCurrency: currency }); setSaved(true); }}>Save</Button>
          {saved && <span style={{ marginLeft: 8 }}>Saved.</span>}
        </section>
      </div>
    </CostShell>
  );
}
