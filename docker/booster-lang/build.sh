#!/usr/bin/env bash
# Build the booster language image for the NATIVE arch (add --platform linux/amd64,linux/arm64 + --push for release).
set -euo pipefail
cd "$(dirname "$0")"
TAG=${1:-vyomi/booster-lang:dev}
j() { jq -r "$1" versions.json; }
docker build -t "$TAG" \
  --build-arg PYTHON_IMAGE="python:$(j .python.version)-$(j .python.image_tag_suffix)" \
  --build-arg RUBY_IMAGE="ruby:$(j .ruby.version)-$(j .ruby.image_tag_suffix)" \
  --build-arg PHP_IMAGE="php:$(j .php.version)-$(j .php.image_tag_suffix)" .
docker image ls "$TAG" --format 'size: {{.Size}}'
