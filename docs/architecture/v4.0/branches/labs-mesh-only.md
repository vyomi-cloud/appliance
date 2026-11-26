# v4/labs-mesh-only

Owner decision 2026-11-26: the existing Vyomi Labs course ("Build the Enterprise Facilities agent") is a Pro/Max Mesh-only course again. The Nano
edition was a filtered copy of it and is removed; a separate course built for Nano users is on `v4/nano-agent-course`.

- `wasm/labs/labs.js` always loads `data/<cloud>.json`, shows "Deploying needs a Mesh" and gates Deploy on a Mesh or the Vyomi runner for every cloud.
- `vyomilabs/content/build_courses.py` emits only the Mesh edition; `wasm/labs/data/{aws,gcp,azure}-nano.json` are deleted.
- Course content is unchanged (aws 85 blocks, gcp 89, azure 95).
- Not changed: the Nano Lambda SDK sandbox, Cognito/WAF/authorizer backends, chapter 14 and the Terraform fix stay on trunk.
