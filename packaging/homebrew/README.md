# Homebrew packaging

This directory contains the Homebrew formula scaffold for Vyomi.

## Intended flow

1. Publish a release tarball for Vyomi.
2. Run `bash ./scripts/build-release.sh`.
3. Run `bash ./scripts/update-homebrew-formula.sh <sha256>`.
4. Update `Formula/cloud-learn.rb` with the release `url` and `sha256`.
5. Add the formula to a Homebrew tap.
6. Install with:

```bash
brew install cloud-learn
```

## What the formula installs

- `cloud-learn` launcher in `bin`
- the appliance Compose bundle
- the CloudSim sidecar source
- the simulator backend
- docs and scripts

## Runtime expectations

The installed launcher expects:

- Multipass

The Homebrew package defaults to appliance mode. The launcher brings up the
local Multipass VM and then starts the full Vyomi stack inside that VM.
The source checkout also uses the same appliance launcher:

```bash
bash ./scripts/cloud-learn up
```
