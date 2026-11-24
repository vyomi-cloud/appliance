Fixture repository for the scan parity test (`TestHostedScanParityWithLocalScan`,
docs/architecture/v4.0/HOSTED-MCP-IMPLEMENTATION-PLAN.md §6).

A small project that uses all three clouds from Python, Node.js, Java, Go and Terraform, plus a file that already
has endpoint overrides. The local `vyomi_scan_repo` walk and the hosted split (`get_scan_rules` run with Go's
regexp, then `summarize_scan_hits`) must reach the same per-service verdicts over these files.

Not a working project: the code only has to match the scan rules.
