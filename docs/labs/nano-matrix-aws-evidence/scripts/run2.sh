#!/bin/zsh
EV=/Users/sudhirganti/Applications/simulator/appliance-labsmx-aws/docs/labs/nano-matrix-aws-evidence
for M in llama3.2-1b qwen2.5-1.5b; do
  FREE=$(df -g / | tail -1 | awk '{print $4}'); if [ "$FREE" -lt 4 ]; then echo "DISK LOW $FREE GB, stopping" >> /private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/models2.log; exit 3; fi
  echo "== $M free=${FREE}G" >> /private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/models2.log
  MODEL=$M CH=1,2,3,4,5,6 PRELUDE=/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/prelude.py PROBE=/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/probe.py PROF=/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/prof-m2 OUT=$EV/nano-model-${M//./}.jsonl node plumb.mjs >> /private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/models2.log 2>&1
  rm -rf /private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/prof-m2
done
echo ALLDONE >> /private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/m/models2.log
