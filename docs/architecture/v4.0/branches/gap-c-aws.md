# v4/gap-c-aws

Class C (honest-forever) AWS gaps.

- Design: `core/ec2_ultraservers_core.py` books Capacity Blocks against a host-sized instance pool (`VYOMI_CAPACITY_POOL_MB`, default half of RAM). Each block creates a real EC2 Capacity Reservation (`core/ec2_ops_core`) that RunInstances consumes: Nano via the ec2_ops wrapper, the offline appliance via `admit_launch()` called from `server.py` `_ec2_query_run_instances` (counts Docker-backed instances).
- Labels: Capacity Blocks `limited` ("Dev Simplified"); UltraServers / accelerator capacity `not_simulated` with "Not in scope" wording (physical hardware).
- Open issues: instances are not auto-terminated when a block ends; offline path verified by unit test of `admit_launch`, not against live Docker launches; no GPU detection (accelerator types are refused outright).
