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
      // Every tab strip gets a full divider. Page-level strips run edge to edge of the content card,
      // like PageHeader's divider (mx -3 past the page's 24px padding); strips inside a Paper
      // (Section, Dialog) keep to their box. Active-tab indicator sits on this line.
      MuiTabs: {
        styleOverrides: {
          root: {
            borderBottom: `1px solid ${dark ? "#444746" : "#e1e3e1"}`,
            "&:not(.MuiPaper-root *)": { marginLeft: -24, marginRight: -24, paddingLeft: 24, paddingRight: 24 },
          },
        },
      },
      // Page-level horizontal rules run edge to edge of the content card, however narrow the form
      // wrapper they sit in (create/config pages cap their width): <main>'s content width (100cqw) plus
      // its 24px padding each side, from its left edge. Rules inside a Paper (Section, Dialog, Menu) keep to it.
      MuiDivider: {
        styleOverrides: {
          root: {
            "&:not(.MuiDivider-vertical):not(.MuiPaper-root *)": { width: "calc(100cqw + 48px)", maxWidth: "none", marginLeft: -24, marginRight: 0, alignSelf: "flex-start" },
          },
        },
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
      // A FormControl's InputLabel takes its offset from the control's size: left at medium, the
      // label of an empty small Select rests too low in the field.
      MuiFormControl: { defaultProps: { size: "small" } },
      MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
      MuiDialog: { styleOverrides: { paper: { borderRadius: 16 } } },
      MuiTooltip: { defaultProps: { arrow: false } },
    },
  });
}
