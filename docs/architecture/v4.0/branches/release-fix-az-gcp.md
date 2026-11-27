# v4/release-fix-az-gcp

Base: v4/release-fixes-4-1-2. Fixes for the v4.1.1 release-check failures in the Azure/GCP Nano lane. Tests/harness only; no consoles/core change, so no bundle rebuild.

- Nano CLI `az rest PUT Microsoft.Compute/virtualMachines`: Nano rejects the Ubuntu marketplace image by design (PlatformImageNotFound, Nano boots only Alpine). tests/cli/azure-cli-smoke.sh now sends the Nano Alpine image when TARGET=nano.
- nano-ui-azure-monitor: the alert-rule row sat under the fixed bottom dock (welcome banner pushes the table down), the checkbox click was intercepted. Row is scrolled to centre before ticking (monitor.mjs, shared uiRowDelete).
- nano-ui-gcp-redis: waits lengthened and the post-delete check polls; failure not reproducible deterministically.
