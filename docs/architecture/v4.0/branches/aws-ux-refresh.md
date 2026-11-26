# aws-ux-refresh

Applies the AWS console's 2026 visual refresh to every AWS service page in the v4 AWS console.

- Source of truth: `consoles/src/aws/kit/theme.js` (Cloudscape design tokens; one place, all services).
- Measured from the live AWS Management Console (IAM > Create policy): page `#f9f9f9`; cards white with a `#e3e1de` hairline border, 2px radius, no shadow; text `#201e1b`; primary button `#262420` on `#f9f9f9` text, 4px radius; secondary button `#f9f9f9` with `#948f88` border and `#3e3b35` text; font stack leads with "Ember Modern Text UI"/"Amazon Ember" (proprietary: falls back to Roboto/Helvetica when not installed).
- Default density is now Compact (existing saved preferences are kept).
- Not changed: the top bar (shared, dark, carries the Vyomi logo) and the GCP/Azure consoles.
- Verified: bundle built; S3, EC2, IAM pages screenshotted against the new tokens (static preview, Nano boot scripts stubbed). Not run: the UI smoke suites.
