# v4/release-fix-aws-ui

Fixes the 8 failing "Console UI (Nano) - aws" suites of the v4.1.1 release checks.

- Six suites (`nano-ui-aws-ec2-detail-tabs`, `-real-tabs`, `-rds-connectivity-tabs`, `-vpc-details-tab`, `nano-ui-drawer`, `nano-ui-aws-rds-persist`) failed in 0.0s: `suites.json` still pointed at the legacy v3 scripts (`validate-aws-ec2-detail-tabs.mjs`, `validate-drawer.mjs`, ...) that were deleted by the v4 retarget (3a2fcc8a2). Commands now run `validate-aws-v4-detail.mjs` (ONLY=ec2 / rds / vpc,subnet,sg,igw,rtb / all) through `tests/conformance/nightly/aws-v4-detail.mjs`, and `validate-v4-nano-drawer.mjs` / `validate-aws-v4-nano-persist.mjs` through `v4-nano-run.mjs`.
- `bidi-aws-cli-ui`: 60 s timeout is shorter than the ~3.5 min run; raised to 600 s.
- UI-create steps (S3, SQS, SNS, DynamoDB, EventBridge) failed because the fixed "Share feedback" button (consoles/feedback-widget.js, bottom-right) sat on top of the right-aligned primary action of every create form and intercepted the click. The widget now sits bottom-left. Built outputs regenerated with `cd consoles && node build.mjs`.
