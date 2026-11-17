#!/bin/sh
# usage: run.sh <tofu args...>   (runs OpenTofu in Linux, trusting the spike cert)
cd "$(dirname "$0")" && docker run --rm -v "$PWD":/w -w /w -e TF_IN_AUTOMATION=1 ghcr.io/opentofu/opentofu:latest "$@" -no-color
