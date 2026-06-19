# SPIKE: Docker-backed compute instance (end-to-end)

**Status: PASS.** Run live on the OUTER appliance VM (`cloudlearn-appliance`,
aarch64, Docker 29.1.3, overlayfs, cgroup v2) on 2026-06-19.

Goal: prove the EC2/GCE/Azure-VM instance lifecycle that `server.py` does today
via **LXD + multipass + the runtime bridge** can be served by **Docker** instead
— the first step of "move away from LXD to simplify the appliance."

## What it proves

| Capability | LXD today | Docker (this spike) | Result |
|---|---|---|---|
| Create an "instance" | `lxc launch` | `docker run -d --privileged -v vol:/var/lib/docker` | ✓ |
| Boot / ready signal | container running | inner `dockerd` up in **16s** | ✓ |
| Shell in | `lxc exec` / ssh | `docker exec` (sshd layers on top, see Dockerfile) | ✓ |
| **Docker-in-instance** (the A1 feature) | `security.nesting=true` | privileged DinD | ✓ ran a container *inside* the instance |
| Persistence across stop/start | native | writable layer + named volume | ✓ marker + inner image survived |
| Status + IP for the SPA | `lxc list` | `docker inspect` | ✓ `running` / `172.17.0.2` |
| Terminate + delete disk | `lxc delete` | `docker rm -f` + `volume rm` | ✓ |

Run it anywhere with Docker: `bash run_spike.sh`
(network-light: only `docker:dind` is pulled; the inner image is side-loaded via
`docker save | docker load`, so the instance's inner daemon needs no network.)

## Findings (brutally honest)

- **The "VM semantics are hard in Docker" risk is mostly tractable.** Stop/start
  persistence is free; DinD works; full `systemd` is **not** required — `tini`/
  `docker-init` as PID1 supervising `sshd` + `dockerd` covers the instance UX and
  is *simpler* than systemd-in-Docker.
- **The real cost is `--privileged`.** DinD needs it, which is weaker isolation
  than unprivileged LXD. Fine for a single-user laptop/dogfood appliance. For a
  **multi-tenant hosted** Vyomi, use rootless-DinD or sysbox/gVisor/Kata instead
  of privileged — decide this before the hosted path, not after.
- **SSH** wasn't literally exercised (used `exec`); it's just `sshd` in the image
  + key injection, which ports directly from the existing `_multipass_ssh_*`
  code. `Dockerfile.instance` shows the shape.
- **boot is ~16s** for dind cold — comparable to LXD cold launch, far better than
  the multipass-VM path the launcher fights with.

## The seam (`backend.py`) — what actually ports

`server.py`'s ~45 `_lxd_*` / `_multipass_*` functions collapse behind one ABC:

    ComputeBackend.create / start / stop / reboot / terminate / status / ipv4 / exec / ssh_info

`DockerComputeBackend` implements it today. This is the part that "ports to
WebVM" — **not dockerd** (which cannot run inside WebVM: no kernel namespaces/
cgroups in the WASM sandbox). A future browser/"Lite" build implements the SAME
ABC with an in-process backend (no real containers, feature-gated compute). The
interface is the portable asset; the Docker impl is just today's host.

## Port plan (LXD → Docker)

1. Promote `backend.py` into `core/compute/` and flesh out `DockerComputeBackend`
   (sshd + key injection from `_multipass_ssh_identity`; bake the aws/gcloud/az
   CLIs as image layers instead of `_lxd_clouds_clis_bootstrap_async`).
2. Repoint `_ensure_container` / `_start_instance_command` / stop / reboot /
   terminate / status / ipv4 call sites at the backend.
3. Delete the `_lxd_*` + `_multipass_*` functions, `core/runtime_bridge.py`, and
   the bridge plumbing; strip multipass/socat/mDNS from `scripts/cloud-learn`.
4. Pick the isolation model for the hosted path (privileged DinD vs sysbox).

## Cleanup

The runner removes its container + volume on exit (trap). Nothing persists.
