# v4/console-look

Base: origin/v4/iam-pickers-integ. Look-only token changes, no layout rewrites.

- AWS: shared TopBar (consoles/src/aws/pages/TopBar.jsx) is light (#fafafa, hairline border, dark text/icons, white search, dark Vyomi wordmark via logo.js bar:"light"). Dropdown menus and the Services drawer stay dark.
- GCP (consoles/src/gcp/theme.js), measured read-only from the live console: page/chrome #f1f5fd, text #1b2e5d / #475569, primary+links #3d60b8, search pill #e7ecf5, active nav #deecfa, divider #dfe5f0, button radius 12, font "Google Sans Flex" first.
- Azure: top bar #3376cd (sampled from live portal), pills #e8f2fa. Fluent web themes otherwise unchanged.
- Reference tokens + screenshots: session scratchpad refshots/{gcp,azure}/tokens (tokens.json, page.png).
