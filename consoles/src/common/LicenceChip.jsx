/* Licence chip for model lists/cards (Bedrock Model catalog, Vertex Model Garden, Foundry model lists): the model's licence, "Built with Llama" for
 * Llama-family models and a visible non-commercial flag. Cloud-neutral markup (inherits font/colour) so it sits in Cloudscape, MUI and Fluent.
 * ENGINEERING DRAFT labelling, not legal advice: the full text is on the Notices & licences page (#/notices). Data: core/ai_model_catalog.py
 * (generated from tools/notices/notices.json); an API list may carry it as the additive `vyomiLicense` field. */
import { byId } from "./aiModels.js";

const OUT = { display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: 12, lineHeight: 1.4 };
const CHIP = { display: "inline-block", padding: "0 6px", border: "1px solid color-mix(in srgb, currentColor 35%, transparent)", borderRadius: 3, textDecoration: "none", color: "inherit", whiteSpace: "nowrap" };

export const shortLicense = (l) => (l.licenseId && !String(l.licenseId).startsWith("LicenseRef") ? l.licenseId : String(l.license || "").replace(/ License$/, "").replace(/ Terms of Use$/, " Terms of Use"));

/** The licence fields of a model: the API's vyomiLicense, else the model record, else the bundled catalogue by catalogue id. */
export function licenceOf(m, id) {
  const l = (m && (m.vyomiLicense && m.vyomiLicense.license ? m.vyomiLicense : m.license ? m : null)) || (id ? byId(id) : null);
  return l && l.license ? l : null;
}

export default function LicenceChip({ m, id }) {
  const l = licenceOf(m, id);
  if (!l) return null;
  return (
    <span style={OUT} data-testid="licence-chip">
      <a href="#/notices" style={CHIP} title={`${l.license}. Open Notices & licences.`} data-testid="licence-name">{shortLicense(l)}</a>
      {l.builtWithLlama && <b data-testid="built-with-llama">Built with Llama</b>}
      {l.commercialUse === false && <span data-testid="non-commercial-flag" style={{ ...CHIP, color: "#b3261e", borderColor: "#b3261e", fontWeight: 600, whiteSpace: "normal" }}>{l.licenseFlag || "Non-commercial research licence: not for paid use"}</span>}
    </span>
  );
}
