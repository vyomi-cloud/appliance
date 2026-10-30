/* AWS lens theme: the console's orange primary actions (Cloudscape's default is blue). */
import { applyTheme } from "@cloudscape-design/components/theming";

export function applyAwsTheme() {
  applyTheme({
    theme: {
      tokens: {
        colorBackgroundButtonPrimaryDefault: { light: "#ff9900", dark: "#ff9900" },
        colorBackgroundButtonPrimaryHover: { light: "#fa6f00", dark: "#ffac31" },
        colorBackgroundButtonPrimaryActive: { light: "#ec7211", dark: "#ec7211" },
        colorTextButtonPrimaryDefault: { light: "#0f141a", dark: "#0f141a" },
        colorTextButtonPrimaryHover: { light: "#0f141a", dark: "#0f141a" },
        colorTextButtonPrimaryActive: { light: "#0f141a", dark: "#0f141a" },
      },
    },
  });
}
