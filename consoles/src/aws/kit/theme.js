/* AWS lens theme: the console's 2026 visual refresh, applied to every AWS service page from this one place.
   Measured from the live AWS Management Console (IAM > Create policy): compact, flat white cards with a light warm-gray hairline
   border and no shadow on a near-white page, black primary buttons, gray-outlined secondary buttons, 4px button radius.
   (Cloudscape's default is the older blue / shadowed-card look; the console's orange primary was the previous theme.) */
import { applyTheme } from "@cloudscape-design/components/theming";

const INK = "#201e1b", BLACK = "#262420", BORDER = "#e3e1de", PAGE = "#f9f9f9", BTN_BORDER = "#948f88", BTN_TEXT = "#3e3b35";
const FONT = '"Ember Modern Text UI", "Amazon Ember", Roboto, "Helvetica Neue", Arial, sans-serif';

export function applyAwsTheme() {
  applyTheme({
    theme: {
      tokens: {
        fontFamilyBase: FONT,
        // page + cards: white boxes with a light gray border, no elevation
        colorBackgroundLayoutMain: { light: PAGE, dark: "#0f1419" },
        colorBackgroundContainerContent: { light: "#ffffff", dark: "#161d26" },
        colorBackgroundContainerHeader: { light: "#ffffff", dark: "#161d26" },
        colorBorderContainerTop: { light: BORDER, dark: "#2a323d" },
        colorBorderDividerDefault: { light: BORDER, dark: "#2a323d" },
        colorTextBodyDefault: { light: INK, dark: "#e9ebed" },
        borderRadiusContainer: "2px",
        shadowContainer: { light: "none", dark: "none" },
        shadowContainerActive: { light: "none", dark: "none" },
        shadowPanel: { light: "none", dark: "none" },
        // buttons: black primary, outlined secondary
        borderRadiusButton: "4px",
        borderRadiusInput: "2px",
        colorBackgroundButtonPrimaryDefault: { light: BLACK, dark: "#f9f9f9" },
        colorBackgroundButtonPrimaryHover: { light: "#3e3b35", dark: "#ffffff" },
        colorBackgroundButtonPrimaryActive: { light: "#000000", dark: "#e3e1de" },
        colorTextButtonPrimaryDefault: { light: "#f9f9f9", dark: BLACK },
        colorTextButtonPrimaryHover: { light: "#ffffff", dark: BLACK },
        colorTextButtonPrimaryActive: { light: "#ffffff", dark: BLACK },
        colorBorderButtonNormalDefault: { light: BTN_BORDER, dark: "#6b7580" },
        colorTextButtonNormalDefault: { light: BTN_TEXT, dark: "#e9ebed" },
        colorBackgroundButtonNormalDefault: { light: PAGE, dark: "transparent" },
      },
    },
  });
}
