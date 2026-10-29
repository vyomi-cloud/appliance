#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export LANG=C

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${CLOUD_LEARN_VERSION_FILE:-${ROOT_DIR}/VERSION}"
FORMULA_FILE="${VYOMI_FORMULA_FILE:-${CLOUD_LEARN_FORMULA_FILE:-${ROOT_DIR}/packaging/homebrew/Formula/vyomi.rb}}"
RELEASE_BASE_URL="${CLOUD_LEARN_RELEASE_BASE_URL:-https://example.com/releases}"

if [ ! -f "$VERSION_FILE" ]; then
  printf 'Version file not found: %s\n' "$VERSION_FILE" >&2
  exit 1
fi

if [ ! -f "$FORMULA_FILE" ]; then
  printf 'Formula file not found: %s\n' "$FORMULA_FILE" >&2
  exit 1
fi

VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
if [ -z "$VERSION" ]; then
  printf 'Version file is empty: %s\n' "$VERSION_FILE" >&2
  exit 1
fi

if [ $# -lt 1 ]; then
  printf 'Usage: %s <sha256>\n' "${BASH_SOURCE[0]}" >&2
  exit 2
fi

SHA256="$1"
URL="${RELEASE_BASE_URL}/vyomi-${VERSION}.tar.gz"

python3 - <<'PY' "$FORMULA_FILE" "$URL" "$SHA256" "$VERSION"
from pathlib import Path
import sys

formula_path = Path(sys.argv[1])
url = sys.argv[2]
sha256 = sys.argv[3]
version = sys.argv[4]

text = formula_path.read_text()
text = text.replace('url "https://example.com/releases/cloud-learn-0.1.0.tar.gz"', f'url "{url}"')
text = text.replace('sha256 "0000000000000000000000000000000000000000000000000000000000000000"', f'sha256 "{sha256}"')
text = text.replace('homepage "https://example.com/cloud-learn"', f'homepage "https://example.com/cloud-learn/v{version}"')
formula_path.write_text(text)
PY

printf 'Updated %s\n' "$FORMULA_FILE"
printf '  url: %s\n' "$URL"
printf '  sha256: %s\n' "$SHA256"
