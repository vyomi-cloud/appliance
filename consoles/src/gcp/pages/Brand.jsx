/* Vyomi brand for the GCP lens top bar: Vyomi mark + "vyomi | Google Cloud" (no third-party
 * logos or marks). Colours follow the light/dark theme. */
import { useTheme } from "@mui/material/styles";
import { wordmark } from "../../common/brand.js";

export function Brand() {
  const dark = useTheme().palette.mode === "dark";
  const mark = wordmark("Google Cloud", { bar: dark ? "dark" : "light" });
  return (
    <a href="#/" aria-label="Vyomi Google Cloud — home" style={{ display: "inline-flex", alignItems: "center", padding: "0 4px" }}>
      <img src={mark.src} alt="vyomi.cloud | Google Cloud" height={30} style={{ display: "block" }} />
    </a>
  );
}
