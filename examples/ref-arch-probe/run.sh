#!/bin/zsh
# usage: run.sh NN
R=/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/6a85ca48-505a-4ca3-8031-1be6b68529c2/scratchpad
cd $R/appliance-probe-gcp/examples/ref-arch-probe/gcp
PYTHONUNBUFFERED=1 PYTHONPATH=$R/appliance-probe-gcp $R/probe-gcp-venv/bin/python probe_$1_*.py 2>$R/err_$1.log; echo "exit=$?"
