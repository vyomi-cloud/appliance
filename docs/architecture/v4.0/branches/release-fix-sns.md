# v4/release-fix-sns

Fixes the 3 failing SDK suites in the v4.1.1 release-checks report.

- `offline-sdk-go-aws-sns` / `offline-sdk-java-aws-sns`: "Publish was delivered to the email subscription (message log)".
  Push protocols are delivered asynchronously by the JetStream-backed worker (core/sns_delivery.py) in the full stack, so a single
  read of /api/aws/sns/deliveries right after Publish races it. Both suites now poll up to 10s (as one must on real SNS).
- `offline-sdk-python-aws`: `aws.s3.minio:object.get.via-minio-direct` needs MinIO on host :9100, which docker-compose.cloudlite.yml
  does not publish. An unreachable port is now a SKIP, not a FAIL.

Tests only; no core/ change, so no wasm/core regeneration.
