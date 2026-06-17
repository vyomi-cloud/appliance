#!/bin/bash
# Firestore emulator wrapper with REST-API-driven export-on-SIGTERM.
#
# The Firestore emulator's --export-on-exit flag was found to be a NO-OP
# when the jar is invoked directly (the export hook is implemented in
# the gcloud Python CLI wrapper, NOT in the jar). When invoked via gcloud
# the wrapper swallows SIGTERM before the JVM can act on it. Either way:
# --export-on-exit can't be relied on.
#
# This wrapper does it the only way that actually works:
#   1. Start the emulator (gcloud or jar — doesn't matter)
#   2. Trap SIGTERM/SIGINT in bash
#   3. On trap, hit the emulator's REST endpoint
#         POST /emulator/v1/projects/<id>:export
#      with export_directory pointing at our volume-backed /data dir
#   4. THEN forward SIGTERM to the emulator and wait for it to exit
#
# On boot, scan /data/firestore-export for the most recent
# *.overall_export_metadata file and import it before serving traffic.
# This is reliable — same code path used by Google's own integration
# tests.

set -eu

DATA_DIR="${DATA_DIR:-/data}"
EXPORT_DIR="$DATA_DIR/firestore-export"
HOST_PORT="${FIRESTORE_HOST_PORT:-0.0.0.0:8080}"
PROJECT="${FIRESTORE_PROJECT:-cloudlearn}"
LOCAL_PORT="${HOST_PORT##*:}"

mkdir -p "$EXPORT_DIR"

# Find the MOST RECENT prior export (sort by mtime, descending).
# Empty-string-safe if no exports exist yet.
METADATA_FILE=$(find "$EXPORT_DIR" -name "*.overall_export_metadata" \
                  -type f -printf '%T@ %p\n' 2>/dev/null \
                | sort -nr | head -1 | cut -d' ' -f2- || true)

# Build the gcloud command. Using gcloud because the jar's argument
# surface keeps shifting between SDK versions — gcloud is the stable face.
GCLOUD_ARGS="--host-port=$HOST_PORT --project=$PROJECT"
if [ -n "${METADATA_FILE:-}" ] && [ -f "$METADATA_FILE" ]; then
  echo "==> Firestore: importing prior export: $METADATA_FILE"
  GCLOUD_ARGS="$GCLOUD_ARGS --import-data=$METADATA_FILE"
else
  echo "==> Firestore: no prior export, fresh start"
fi

# Start emulator in background so the bash script can sit waiting and
# handle signals. We deliberately do NOT exec — the script's signal
# handler is what makes export-on-SIGTERM work.
gcloud beta emulators firestore start $GCLOUD_ARGS &
child=$!

# Signal handler — REST-export then SIGTERM the child.
_graceful_export_and_exit() {
  echo "==> SIGTERM received; calling export REST endpoint..."
  # Up to 30s for the export call (large collections take time).
  if command -v curl >/dev/null 2>&1; then
    curl -s -X POST -m 30 \
      "http://127.0.0.1:${LOCAL_PORT}/emulator/v1/projects/${PROJECT}:export" \
      -H "Content-Type: application/json" \
      -d "{\"database\":\"projects/${PROJECT}/databases/(default)\",\"export_directory\":\"${EXPORT_DIR}\"}" \
      > /tmp/firestore-export.out 2>&1 || true
    echo "==> Export REST response: $(cat /tmp/firestore-export.out | head -c 200)"
  else
    echo "==> curl not present; cannot trigger REST export — state will be lost"
  fi
  echo "==> Forwarding SIGTERM to firestore emulator (pid=$child)..."
  kill -TERM "$child" 2>/dev/null || true
  # Also kill any pythons + javas underneath gcloud since the gcloud Python
  # wrapper has been observed to leak the JVM as an orphan.
  pkill -TERM -P "$child" 2>/dev/null || true
  wait "$child" 2>/dev/null || true
  echo "==> Firestore emulator shut down cleanly."
  exit 0
}
trap _graceful_export_and_exit TERM INT

# Sit in a wait loop until the child exits (either naturally or via signal).
# Plain `wait $child` returns immediately on signal — wrap so we re-enter.
while kill -0 "$child" 2>/dev/null; do
  wait "$child" 2>/dev/null || true
done
echo "==> Firestore emulator (pid=$child) exited."
