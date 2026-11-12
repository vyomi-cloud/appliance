/* Step 1 of Create Function App: pick a hosting option. Only Flex Consumption's wizard was
 * captured in the spec (gaps_note); the other options route to the same wizard — Vyomi models
 * one hosting plan shape (a Dynamic/FlexConsumption Function App), so picking Consumption /
 * Functions Premium / App Service / Container Apps environment here still creates a real,
 * working function app rather than a dead end. */
import { useState } from "react";
import { Button, Radio, RadioGroup } from "@fluentui/react-components";
import { navigate } from "../../../common/router.js";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";

const OPTIONS = ["Flex Consumption", "Consumption", "Functions Premium", "App Service", "Container Apps environment"];

export default function CreateFunctionAppHosting() {
  const [hosting, setHosting] = useState("Flex Consumption");
  return (
    <>
      <TitleRow title="Create Function App" glyph={<Glyph id="functionapp" />} closeHref="#/functionapp" />
      <div className="vy-page" style={{ maxWidth: 760 }}>
        <section className="vy-form-section">
          <h3>Select a hosting option</h3>
          <RadioGroup value={hosting} onChange={(_, d) => setHosting(d.value)} aria-label="Hosting option">
            {OPTIONS.map((o) => <Radio key={o} value={o} label={o} />)}
          </RadioGroup>
        </section>
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <Button appearance="primary" onClick={() => navigate("functionapp", "create", "flex")}>Select</Button>
          <Button as="a" href="#/functionapp">Cancel</Button>
        </div>
      </div>
    </>
  );
}
