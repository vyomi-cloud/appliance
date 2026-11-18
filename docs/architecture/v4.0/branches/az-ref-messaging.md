# v4/az-ref-messaging (Azure reference architecture, lane 3)

Lane brief: Service Bus store unification and live delivery, Event Grid delivery to functions, AI Search indexer fill, Content Safety.
Evidence: `docs/architecture/v4.0/REF-ARCH-PROBE-AZURE.md` (components 2, 5, 12). Every item is proved with the unmodified Azure SDKs.

## Changes
### 1. Service Bus: one entity store
- Before: ARM wrote ARM records only, the REST wire wrote the Azure space slot, the default AMQP listener (`core/servicebus_amqp`, the "lease" stack) read a third store (`core.azure_servicebus_runtime`, sqlite). An ARM-created topic was `amqp:not-found`.
- Now: `core/azure_servicebus_core.arm_sync/arm_drop` mirror every ARM queue / topic / subscription / rule PUT and DELETE (and namespace / resource-group cascade) into the router's `az_sb` store: the same store the REST wire, Event Grid Service Bus destinations and the AMQP listener serve. Hooks: `AzureArm._sb_mirror` (core engine), `providers/azure_services._deprovision_on_delete` (appliance DELETE path), `AwsWireRouter` sets `az_arm.sb_store` for Nano. A new subscription also gets the visible `$Default` ARM rule record (deleting it via ARM empties the broker rule set, as on real Service Bus).
- The default AMQP listener is now the full engine (`routes/azure_servicebus_amqp.py` + `core/azure_servicebus_amqp.py`): queues and topics, live delivery to attached receivers, sessions, scheduled messages, rules, `$management`. The "lease" stack mounts only with `VYOMI_SB_AMQP_STACK=lease` (resolves V4.0.0-KNOWN-ISSUES AZ-11 for the default path).
### 2. Live delivery
- Fixed by the above: the full engine pumps credit-holding links when another connection or the REST wire enqueues. The old lease stack handed messages only inside the receiving connection's own flow/transfer callbacks, so a late message was never delivered to an attached receiver and a queue receiver failed (`subscription 'q1' not found`).
- Tests (real SDKs): `tests/conformance/test_azure_ref_servicebus_sdk.py` (sync iterator, `receive_messages(max_wait_time)`, async `async for`, renew / abandon / dead-letter + DLQ, `schedule_messages`, sessions, ARM SQL rule filters, REST-created entity over AMQP, ARM delete).
- Harness: `tests/conformance/_az_ref_harness.py` (real `server.py` in-process; fresh state).

## Design decisions
- There is no open-source Service Bus emulator we can run (Microsoft's is not viable: Java management plane is .NET-only, amd64 SQL, footprint/EULA). The broker is Vyomi's own core behind our pure-Python AMQP 1.0 wire. We never claim a real engine.
- The store is namespace-global (the AMQP address and the REST wire carry no namespace); the ARM namespace name is not part of the entity key.
- ARM -> data plane is the mirrored direction; the control plane never fails if the mirror throws.

## Open issues
- An entity created only over the REST wire is not listed by `azure-mgmt-servicebus` (no data plane -> ARM mirror).
- `core/console_azure_servicebus.py` (legacy console facade) still syncs from the old runtime sqlite store; the v4 consoles use the wire.
- Siftly's 5 canonical topics are no longer auto-created on the default listener (they were in the runtime store).
- Pre-existing on trunk: `test_relay_cores_parity.py` fails on `azure_security_automations_core.py` missing from `wasm/relay/nano-endpoint.html` CORES (not this lane).
