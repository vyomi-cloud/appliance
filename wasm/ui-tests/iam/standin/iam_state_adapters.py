"""STAND-IN host adapters (the real ones: core/iam_state_adapters.py, enforce-mesh WP). Principal = the access key id's user."""
import re
POLICIES = {
    "arn:aws:iam::000000000000:user/AKIAVYOMIDUMMY": [{"Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"},
                                                                    {"Effect": "Deny", "Action": ["s3:DeleteBucket"], "Resource": "arn:aws:s3:::locked-*"}]}],
    "arn:aws:iam::000000000000:user/AKIAREADONLY": [{"Statement": [{"Effect": "Allow", "Action": ["s3:Get*", "s3:List*"], "Resource": "*"}]}],
    "arn:aws:iam::000000000000:user/AKIANOTHING": [],
}


def aws_principal(headers, query, store):
    m = re.search(r"Credential=([^/,\s]+)/", headers.get("authorization", ""))
    k = m.group(1) if m else ""
    return {"arn": f"arn:aws:iam::000000000000:user/{k}", "type": "user", "account": "000000000000", "access_key_id": k}


def aws_state(store):
    return {"cloud": "aws", "policies": POLICIES}
