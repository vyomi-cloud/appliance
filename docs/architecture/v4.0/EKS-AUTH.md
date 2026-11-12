# EKS authentication design

## Implemented (core/aws_eks_auth.py, tested in tests/conformance/test_aws_eks_core.py)
`aws eks get-token --cluster-name X` returns `k8s-aws-v1.` + base64url(presigned STS GetCallerIdentity URL), signed headers
`host;x-k8s-aws-id`, payload hash = SHA-256 of the empty string, `X-Amz-Expires` <= 60 s. `verify_token` decodes it, checks the STS host,
the `x-k8s-aws-id` cluster binding, the 15 minute age window, and the SigV4 signature against the access key's secret from the simulator
IAM store. The principal ARN is canonicalised (assumed-role -> role) and mapped through the cluster's access entries to a Kubernetes
username and groups (`authorize`). Verified against tokens minted by botocore and by the real `aws eks get-token`.

## Webhook (aws-iam-authenticator style)
`token_review(cluster, token)` returns a TokenReview v1 body (`authenticated`, `user.username`, `user.groups`). Wiring it into the real
apiserver needs the platform change in EKS-NEEDS.md item 2:
1. server flag `authentication-token-webhook-config-file` (kubeconfig whose server is the simulator TokenReview URL).
2. The apiserver POSTs TokenReview; the simulator verifies and answers; RBAC (access policy -> ClusterRoleBinding) does the rest.
Until then kubectl via the simulator uses admin credentials; verification is exercised by tests only.
