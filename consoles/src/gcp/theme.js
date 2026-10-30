/* GCP-lens theme: Material (MUI 5) tuned to the cloud console's look — tinted chrome
 * (top bar + product nav share a light blue-grey surface), white rounded content card,
 * blue primary, compact 14px type, flat outlined controls. Vyomi branding only. */
import { createTheme } from "@mui/material/styles";

const FONT = '"Google Sans Text", "Google Sans", Roboto, "Segoe UI", "Helvetica Neue", Arial, sans-serif';

export function makeTheme(mode = "light") {
  const dark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: { main: dark ? "#a8c7fa" : "#0b57d0", contrastText: dark ? "#062e6f" : "#fff" },
      secondary: { main: dark ? "#c2e7ff" : "#00639b" },
      error: { main: dark ? "#f2b8b5" : "#b3261e" },
      success: { main: dark ? "#6dd58c" : "#146c2e" },
      warning: { main: dark ? "#ffb95c" : "#9f5b00" },
      background: { default: dark ? "#1b1c1d" : "#f8fafd", paper: dark ? "#131314" : "#ffffff" },
      text: { primary: dark ? "#e3e3e3" : "#1f1f1f", secondary: dark ? "#c4c7c5" : "#444746" },
      divider: dark ? "#444746" : "#e1e3e1",
      chrome: { main: dark ? "#1b1c1d" : "#f8fafd", search: dark ? "#2d2f31" : "#e9eef6", active: dark ? "#004a77" : "#d3e3fd" },
    },
    shape: { borderRadius: 8 },
    typography: {
      fontFamily: FONT,
      fontSize: 13,
      h1: { fontSize: 22, fontWeight: 400, lineHeight: "28px" },
      h2: { fontSize: 18, fontWeight: 400, lineHeight: "24px" },
      h3: { fontSize: 16, fontWeight: 500, lineHeight: "24px" },
      subtitle2: { fontSize: 12, fontWeight: 500 },
      body2: { fontSize: 14, lineHeight: "20px" },
      button: { textTransform: "none", fontWeight: 500, fontSize: 14, letterSpacing: 0.1 },
    },
    components: {
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: { root: { borderRadius: 20, paddingLeft: 16, paddingRight: 16, minHeight: 36 }, text: { paddingLeft: 12, paddingRight: 12 } },
      },
      MuiTab: { styleOverrides: { root: { textTransform: "none", fontSize: 14, fontWeight: 500, minHeight: 48, minWidth: 0, paddingLeft: 16, paddingRight: 16 } } },
      MuiTableCell: {
        styleOverrides: {
          root: { fontSize: 14, paddingTop: 10, paddingBottom: 10, borderColor: dark ? "#444746" : "#e1e3e1" },
          head: { fontWeight: 500, color: dark ? "#c4c7c5" : "#444746", whiteSpace: "nowrap", backgroundColor: dark ? "#131314" : "#fff" },
        },
      },
      MuiTextField: { defaultProps: { size: "small" } },
      MuiSelect: { defaultProps: { size: "small" } },
      MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
      MuiDialog: { styleOverrides: { paper: { borderRadius: 16 } } },
      MuiTooltip: { defaultProps: { arrow: false } },
    },
  });
}
