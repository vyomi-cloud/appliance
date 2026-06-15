#!/usr/bin/env bash
# install-bsl-license.sh — fetch the canonical BSL 1.1 body from a known
# authoritative public deployment (HashiCorp Terraform's LICENSE file)
# and assemble it with Vyomi's specific parameters block. Writes the
# result to ./LICENSE.
#
# Why fetch instead of vendor:
#   1. The BSL 1.1 text body should match the canonical version used
#      by HashiCorp / MariaDB / CockroachDB exactly. Fetching from a
#      known-good source guarantees no transcription drift.
#   2. Verifiable: anyone can re-run this and diff the output.
#   3. Avoids encoding legal text in the install script itself.
#
# Idempotent: re-running overwrites LICENSE with the same content.
#
# Required: curl, bash 3.2+, awk (POSIX)
set -euo pipefail

# HashiCorp Terraform's LICENSE is a well-known canonical BSL 1.1
# deployment. We use the body (the part after the Parameters block)
# verbatim and prepend Vyomi's own Parameters block.
SOURCE_URL="https://raw.githubusercontent.com/hashicorp/terraform/main/LICENSE"

LICENSOR="Vyomi"
LICENSED_WORK="Vyomi Appliance — local multi-cloud simulator"
LICENSED_WORK_URL="https://github.com/vyomi-cloud/appliance"
COPYRIGHT_YEAR="$(date +%Y)"
CHANGE_DATE="$(date -j -v+4y +%Y-%m-%d 2>/dev/null || date -d '+4 years' +%Y-%m-%d)"
CHANGE_LICENSE="Apache License, Version 2.0"

# Vyomi-specific Additional Use Grant. Plain English. Three concrete
# carve-outs: hosting-as-service, tier-enforcement bypass, rebrand-for-sale.
read -r -d '' ADDITIONAL_USE_GRANT <<'GRANT' || true
You may make production use of the Licensed Work, provided that such
use does not include any of the following:

  (a) offering the Licensed Work, or any substantial portion or
      derivative thereof, to third parties as a hosted, managed,
      or otherwise commercial multi-cloud simulator service where
      the value of the offering derives substantially from the
      Licensed Work;

  (b) modifying, removing, disabling, bypassing, or circumventing
      any license validation, tier enforcement, signing verification,
      telemetry, or brand attribution built into the Licensed Work;

  (c) repackaging, rebranding, or otherwise redistributing the
      Licensed Work in modified or unmodified form under a name
      or brand other than "Vyomi" for commercial purposes.

Non-commercial use of the Licensed Work — including personal use,
educational use, security review, and internal evaluation by
organizations — is always permitted.
GRANT

# Fetch the source and verify it's the right thing
echo "→ Fetching canonical BSL 1.1 body from $SOURCE_URL"
tmp="$(mktemp -t bsl11-XXXXXX)"
trap 'rm -f "$tmp"' EXIT

if ! curl -fsSL "$SOURCE_URL" -o "$tmp"; then
  echo "✗ Could not fetch from $SOURCE_URL" >&2
  exit 1
fi
if ! grep -q 'Business Source License 1.1' "$tmp"; then
  echo "✗ Fetched file does not contain 'Business Source License 1.1' header" >&2
  exit 1
fi

# Extract only the canonical body — i.e. start from the "Business Source
# License 1.1" heading and skip HashiCorp's Parameters block at the very
# top. We'll prepend our own Parameters block.
canonical_body="$(awk '/^Business Source License 1.1[[:space:]]*$/{flag=1} flag' "$tmp")"
body_lines="$(echo "$canonical_body" | wc -l | tr -d ' ')"
if [ "$body_lines" -lt 40 ]; then
  echo "✗ Extracted body looks too short ($body_lines lines)" >&2
  exit 1
fi

# Compose the final LICENSE.
cat > LICENSE <<EOF
Vyomi Appliance License

Licensor:             $LICENSOR
Licensed Work:        $LICENSED_WORK
                      $LICENSED_WORK_URL
                      The Licensed Work is (c) $COPYRIGHT_YEAR $LICENSOR.

Additional Use Grant:

$ADDITIONAL_USE_GRANT

Change Date:          $CHANGE_DATE

Change License:       $CHANGE_LICENSE

────────────────────────────────────────────────────────────────────────

For alternative licensing arrangements (commercial hosting,
white-label, OEM, etc.) please contact licensing@vyomi.cloud.

────────────────────────────────────────────────────────────────────────

Notice

The Business Source License (this document, or the "License") is not
an Open Source license. However, the Licensed Work will eventually be
made available under an Open Source license, as stated in this License.

────────────────────────────────────────────────────────────────────────

$canonical_body
EOF

echo "✓ LICENSE written ($(wc -l < LICENSE | tr -d ' ') lines)"
echo ""
echo "Parameters block summary:"
echo "  Licensor:       $LICENSOR"
echo "  Licensed Work:  $LICENSED_WORK"
echo "  Change Date:    $CHANGE_DATE"
echo "  Change License: $CHANGE_LICENSE"
