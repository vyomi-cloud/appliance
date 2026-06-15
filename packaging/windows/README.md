# Windows packaging

This directory contains the Windows installer metadata scaffold for Vyomi.

## Intended flow

1. Build or publish the Vyomi source bundle.
2. Use `packaging/windows/cloudlearn.wxs` as the MSI source.
3. Install the launcher and shortcut into Program Files.
4. Use the installed shortcut to start appliance mode.

## Runtime expectations

- Multipass must be installed on the host.
- The installer launches the appliance VM boundary.
- The appliance VM then runs the simulator, CloudSim, and provider services.

## Notes

This is a starter MSI definition. It can be refined later to add prerequisites
checks, upgrade UI, and bundled dependency detection.
