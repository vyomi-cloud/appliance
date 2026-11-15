# vyomi-endurance findings

Defects the estate harness has surfaced in the simulator. Not fixed on this branch: shared `core/*.py` changes land on the trunk
(CLAUDE.md rule 5). Each entry names the check that caught it, the root cause where known, and the fix. Status: open until a trunk PR lands.

| # | Cloud | Check that caught it | Defect | Root cause / evidence | Suggested fix |
|---|---|---|---|---|---|
| F1 | AWS | apply -> refresh (aws provider 5.x, `aws_vpc`) | `DescribeVpcAttribute enableNetworkAddressUsageMetrics` returns an empty result, so the provider cannot read any VPC back: **every `aws_vpc` apply fails** | `core/vpc_core.py:_describe_vpc_attribute` knows only enableDnsHostnames/enableDnsSupport; any other attribute is answered under the `enableDnsSupport` tag | Support `enableNetworkAddressUsageMetrics` (store flag, default false, also in ModifyVpcAttribute) and return InvalidParameterValue for unknown attributes |
| F2 | AWS | apply timing (`aws_sqs_queue`) | CreateQueue takes ~26 s with the real provider (raw calls are instant) | Hypothesis: `GetQueueAttributes` omits `SqsManagedSseEnabled` (real SQS returns `true` by default since 2022); the provider polls until attributes match, then times out. Verify by returning it | Return `SqsManagedSseEnabled` (default true) and honour it on create/set |
| F3 | Azure | apply/destroy timing (`azurerm_resource_group`) | Create and delete each take ~20 s (3/3 runs); everything else instant | Hypothesis: simulator answers RG PUT with 200 and DELETE with 200+empty; real ARM answers 201 on create and 202 + `Location` (LRO) on delete, so go-azure-sdk's poller waits full default intervals | Return 201 on create, 202 + Location/Azure-AsyncOperation on delete, same as ARM |
| F4 | GCP | **no-change re-plan** after apply (`google_compute_network`) | Provider plans an in-place update forever: `network_firewall_policy_enforcement_order` is absent from the simulator's network GET (real GCP returns `AFTER_CLASSIC_FIREWALL`) | Drift check in the estate gate | Return the default on create/get |

Spikes: `tests/endurance/spikes/{azure,aws,gcp}-tf` (OpenTofu 1.13 in a Linux container; see `run.sh`).
Results: Azure rg+vnet PASS (apply, no-diff, destroy, re-apply). GCP bucket+topic+network apply/destroy PASS, re-plan FAILS (F4).
AWS s3+sqs apply PASS (F2 slow); vpc FAILS (F1), so subnet/route/SG coverage is blocked behind F1.
