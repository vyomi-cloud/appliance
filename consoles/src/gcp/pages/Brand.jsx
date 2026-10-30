/* Vyomi brand for the GCP lens top bar: Vyomi mark + "vyomi | Google Cloud" (no third-party
 * logos or marks). Colours follow the light/dark theme. */
import { useTheme } from "@mui/material/styles";
import { wordmark } from "../../common/brand.js";

export function Brand() {
  const dark = useTheme().palette.mode === "dark";
  const mark = wordmark("Google Cloud", dark
    ? { text: "#e8eaed", sub: "#bdc1c6", divider: "rgba(255,255,255,0.3)" }
    : { text: "#202124", sub: "#5f6368", divider: "rgba(0,0,0,0.2)" });
  return (
    <a href="#/" aria-label="Vyomi Google Cloud — home" style={{ display: "inline-flex", alignItems: "center", padding: "0 4px" }}>
      <img src={mark.src} alt="vyomi | Google Cloud" height={28} style={{ display: "block" }} />
    </a>
  );
}
