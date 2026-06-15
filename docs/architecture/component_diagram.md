# Vyomi Component Diagram

Paste this into Mermaid Live:

```mermaid
graph LR
  Browser[Browser]
  Launcher[Launcher script]
  VM[Multipass appliance VM]
  UI[Simulator UI]
  API[FastAPI app]
  Routes[Provider services]
  RuntimeMgr[Runtime manager]
  Bridge[Runtime bridge]
  LXD[LXD]
  CloudSimAPI[CloudSim API]
  CloudSimState[CloudSim state]
  CloudSimEvents[CloudSim events]

  Browser --> UI
  Launcher --> VM
  VM --> UI
  UI --> API
  API --> Routes
  API --> RuntimeMgr
  RuntimeMgr --> Bridge
  Bridge --> LXD
  API --> CloudSimAPI
  CloudSimAPI --> CloudSimState
  CloudSimAPI --> CloudSimEvents
  API --> CloudSimState
  API --> CloudSimEvents
  Routes --> API
```

## Integration Paths

- Browser talks to the simulator UI.
- The launcher starts a Multipass appliance VM.
- The simulator container inside the VM owns the UI, API, and provider routes.
- CloudSim is a separate container inside the VM and stores space-level simulation state.
- Appliance-mode EC2 execution goes through the VM-local runtime bridge to LXD only.
