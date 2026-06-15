# Snap packaging

This directory contains the Snap metadata scaffold for Vyomi.

## Intended flow

1. Build or publish the Vyomi source bundle.
2. Use `packaging/snap/snapcraft.yaml` as the Snap definition.
3. Package the launcher so `cloud-learn` starts in appliance mode by default.
4. Install the snap on Linux with Snap support.

## Runtime expectations

- Multipass must be available on the host.
- The snap is intended to launch the local appliance VM boundary.
- The appliance VM then runs the simulator, CloudSim, and provider services.

## Notes

This is metadata scaffolding. The actual build pipeline can be refined later to
pull only the release artifacts required by the snap.
