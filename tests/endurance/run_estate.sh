#!/bin/sh
# vyomi-endurance: run the five release checks on one estate module.
#   run_estate.sh <module-dir> <endpoint-url> [report.json]
# 1 validate  2 apply  3 re-plan must be a NO-OP (drift)  4 destroy  5 re-apply, then final destroy (rebuild is identical).
# Exit 0 only if every check passed. Every step's wall-clock seconds are recorded: slow steps are findings too (F2/F3 were found that way).
set -u
MOD="$1"; EP="$2"; REPORT="${3:-/dev/null}"
cd "$MOD" || exit 2
VAR="-var=endpoint=$EP"
LOG="${ENDURANCE_LOG_DIR:-${TMPDIR:-/tmp}}/endurance-$(basename "$MOD")"; mkdir -p "$LOG"
rm -f terraform.tfstate terraform.tfstate.backup
fail=0; steps=""
step() { # name, cmd...
  n="$1"; shift; s=$(date +%s); "$@" >"$LOG/$n.log" 2>&1; rc=$?; t=$(( $(date +%s) - s ))
  echo "[$( [ $rc -eq 0 ] && echo PASS || echo FAIL )] $n (${t}s)"; [ $rc -ne 0 ] && fail=1
  steps="$steps{\"step\":\"$n\",\"rc\":$rc,\"seconds\":$t},"
  return $rc
}
step init ./run.sh init
step validate ./run.sh validate
step apply ./run.sh apply -auto-approve -backup=- "$VAR" || true
# a plan that is not a no-op after a clean apply = the simulator returns something the provider cannot reconcile
./run.sh plan -detailed-exitcode "$VAR" >"$LOG/replan.log" 2>&1; rc=$?
if [ $rc -eq 0 ]; then echo "[PASS] replan no-diff"; else echo "[FAIL] replan no-diff (exit $rc: 2 means drift)"; fail=1; fi
steps="$steps{\"step\":\"replan\",\"rc\":$rc},"
step destroy ./run.sh destroy -auto-approve -backup=- "$VAR" || true
step reapply ./run.sh apply -auto-approve -backup=- "$VAR" || true
step final-destroy ./run.sh destroy -auto-approve -backup=- "$VAR" || true
printf '{"module":"%s","endpoint":"%s","passed":%s,"steps":[%s]}\n' "$MOD" "$EP" "$([ $fail -eq 0 ] && echo true || echo false)" "${steps%,}" > "$REPORT"
[ $fail -eq 0 ] && echo "ESTATE CYCLE: PASS" || echo "ESTATE CYCLE: FAIL (logs in $LOG)"
exit $fail
