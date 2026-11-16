#!/bin/sh
# usage: run.sh <tofu args...>  (OpenTofu in Linux, shared provider cache outside the repo)
cd "$(dirname "$0")" && docker run --rm -v "$PWD":/w -w /w -v "${VYOMI_PLUGIN_CACHE:-$HOME/.vyomi-endurance/plugin-cache}":/cache -e TF_PLUGIN_CACHE_DIR=/cache -e TF_IN_AUTOMATION=1 -e TF_LOG ghcr.io/opentofu/opentofu:latest "$@" -no-color
