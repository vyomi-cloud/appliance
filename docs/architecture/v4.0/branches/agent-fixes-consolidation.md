# v4/agent-fixes-consolidation

Owner: appliance session - Started: 2026-11-14 - Base: origin/v4-on-main (c7df83077) - Status: ready to merge

## Purpose
Land the previously local-only commits from the three Nano bi-directional agent runs (AWS, GCP, Azure) on the trunk.

## What is in it
- AWS: re-seed quickstart AMIs when the seeded flag survives without images (trunk already has the stable-id scheme from 7f6d42a9e, kept); genuine-Nano UI<->API suites; terminated instances no longer block DeleteSecurityGroup.
- GCP: console Start/Resume resumes a SUSPENDED VM; instance detail lists attached disks; Nano mode for the v4 round-trips. wasm/v4/gcp rebuilt.
- Azure: genuine-Nano UI action suites (VM power, storage, App Service/Function power, VNet subnets).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| keep trunk's uuid5 AMI ids, add only the re-seed guard | agent's sha256 ids | trunk already shipped uuid5 ids; two schemes would change ids again |

## Open issues
- [ ] Service Bus ARM queues not sendable; Cloud Functions console/v2 API disagree; Vertex generateContent 503; AWS Health tile DynamoDB 403; AWS/Azure coverage partial (owner: next sessions)
