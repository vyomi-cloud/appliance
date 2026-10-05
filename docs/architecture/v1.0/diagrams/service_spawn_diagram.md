# Service Spawn Diagram

This document shows how Cloud Learn starts, how the simulator and CloudSim containers fit together, and how EC2 sandboxes are launched inside the appliance VM.

## Startup Flow

```mermaid
flowchart TB
  U[User browser] -->|HTTP / WebSocket| SIM[simulator container<br/>FastAPI + UI]

  HOST[Host OS<br/>bash or PowerShell launcher] -->|starts| VM[Multipass appliance VM]
  VM -->|runs| BRIDGE[core/runtime_bridge.py<br/>VM-local host process]
  VM -->|starts| DC[docker compose]

  DC --> SIM
  DC --> CS[cloudsim container<br/>CloudSim backbone]

  BRIDGE -->|VM-local runtime API| SIM

  SIM -->|CLOUDLEARN_CLOUDSIM_URL| CS
  SIM -->|API routes| SRV[server.py]
  SRV --> PRV[providers/* routes]
  SRV --> RT[RuntimeManager / appliance-local runtime]
  SRV --> BRIDGE

  RT -->|LXD only inside appliance| LXD[LXD inside VM]
```

## EC2 Launch Sequence

```mermaid
sequenceDiagram
  participant Browser
  participant Simulator as simulator container
  participant Server as server.py
  participant Bridge as VM-local runtime bridge
  participant HostRT as LXD on appliance VM host
  participant CloudSim as cloudsim container

  Browser->>Simulator: POST /api/ec2/instances
  Simulator->>Server: create instance request
  Server->>Server: force LXD backend in appliance mode
  Server->>Server: create instance record (state=pending)
  Server->>CloudSim: sync resource_graph upsert

  Server->>Bridge: request runtime start
  Bridge->>HostRT: run lxc command on appliance VM host
  HostRT-->>Bridge: sandbox started or error
  Bridge-->>Server: success / failure

  alt runtime starts
    Server->>Server: state=running, launch_status=ready
    Server->>CloudSim: sync resource_graph upsert
    Browser->>Simulator: open console
    Simulator->>Server: WebSocket /console
    Server-->>Browser: SSH / exec stream
  else runtime fails
    Server->>Server: launch_status=error, launch_error=...
    Server->>CloudSim: sync resource_graph upsert
    Browser-->>Simulator: launch failed
  end
```

## Component Responsibilities

- `scripts/cloud-learn` and `scripts/cloud-learn.ps1` run on the host OS and launch the appliance VM.
- The appliance VM runs the inner launcher and starts the VM-local runtime bridge.
- `core/runtime_bridge.py` runs on the appliance VM host and executes `lxc`.
- `simulator` is the API and UI container inside the VM.
- `cloudsim` is the simulation backbone container inside the VM.
- `server.py` orchestrates provider APIs and runtime launches.
- `providers/*` hold provider-specific route modules.

## Notes

- EC2 sandboxes are launched inside the appliance VM, not on the laptop host OS.
- Appliance mode uses LXD only for EC2, regardless of the laptop host OS.
- If the VM-local bridge is unreachable, EC2 launches remain pending and the launch status is marked as an error.
