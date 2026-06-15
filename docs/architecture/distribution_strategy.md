# Vyomi Distribution Strategy

## Goal

Make Vyomi easy to install and operate on macOS, Linux, and Windows using one of three familiar patterns:
- package managers,
- `docker compose`,
- or OS-native installers.

The platform should feel like a product, not a hand-wired stack of host processes.

## Recommended Shape

The cleanest operational model is:

1. The host installs a small launcher and Multipass.
2. The launcher creates one durable Multipass VM appliance.
3. The VM runs the full Vyomi runtime.
4. The host only starts, stops, and updates the appliance.

This gives us:
- one installation story,
- one restart boundary,
- and one place where the durable simulation state lives.

## Single Launcher

Vyomi now has one launcher path:

```bash
bash ./scripts/cloud-learn up
```

or on Windows:

```powershell
.\scripts\cloud-learn.ps1 up
```

The launcher starts one durable Multipass VM appliance and then starts the full Vyomi runtime inside that VM from `docker-compose.appliance.yml`.

## Packaging

The packaging targets are wrappers around the same launcher:
- Homebrew
- Snap
- MSI / winget

They all bring up the same appliance boundary and should not reintroduce a separate developer runtime path.

What runs inside the VM:
- simulator UI/API
- CloudSim backbone
- provider emulators
- VM-local runtime bridge
- persistent state
- EC2-like sandboxes backed by LXD

Why:
- the VM becomes the durable boundary,
- host restarts are much less disruptive,
- and the platform no longer depends on host-native runtime wiring after startup.

## What Should Live Where

### Host

Keep the host thin:
- launcher
- VM lifecycle management
- optional port forwarding or SSH tunnel
- package-manager integration

Do not keep the business logic on the host.

### Inside the VM

Keep the runtime self-contained:
- simulator
- CloudSim
- providers
- sandbox runtime
- deployment workspaces
- persistent state

## What To Use For Runtime Orchestration

Recommended:
- `docker compose` inside the VM for the simulator stack
- or `systemd` if you want tighter OS integration

Avoid:
- Multipass inside Multipass
- laptop-side runtime bridges as a long-term dependency

## User Experience

The target UX should be:

1. Install once.
2. Start one command or one app.
3. Open a browser.
4. Create resources locally.
5. Export Terraform.
6. Deploy to real AWS/GCP/Azure when ready.

## Implementation Order

1. Make the appliance VM the first-class runtime.
2. Move durable state into the VM.
3. Start the full runtime stack inside the VM.
4. Keep the host launcher thin.
5. Add installer packaging per OS.
6. Add Terraform export/import workflows.

## Rollout Checklist

This is the execution checklist for the distribution workstream.

- [x] Define the distribution modes: developer, appliance, end-user.
- [x] Persist host OS and bridge metadata in the launcher-written host config.
- [x] Make the launcher expose a distribution mode field in the runtime contract.
- [x] Add a first-class appliance bootstrap path that starts the full stack inside one VM.
- [x] Wire the launcher to route top-level lifecycle commands through appliance mode.
- [x] Make appliance runtime detection ignore host bridge/config and use appliance-local state.
- [x] Add package-manager metadata for macOS, Linux, and Windows installers.
- [x] Add a VM bootstrap health check that fails fast if the appliance cannot reach its internal services.
- [x] Move the remaining runtime assumptions away from the host OS and into the appliance boundary.
- [x] Add a clean UI entry point for the Terraform export / deploy workflow.

## Recommendation Summary

- **Developer path:** `docker compose` or the launcher script.
- **End-user path:** OS-native installer or package manager.
- **Runtime path:** one Multipass VM appliance.
- **Inside the appliance:** simulator, CloudSim, provider services, and sandboxes.

This gives the simplest combination of:
- installability,
- restart safety,
- and future Terraform deployment support.
