from google.cloud import iam_credentials_v1 as ic

import gcp

sa = f"agent-sa@{gcp.PROJECT}.iam.gserviceaccount.com"
r = gcp.authed_session().post(f"{gcp.ENDPOINT}/v1/projects/{gcp.PROJECT}/serviceAccounts", json={"accountId": "agent-sa", "serviceAccount": {"displayName": "facilities agent"}}, timeout=60)
assert r.status_code in (200, 201, 409), r.text
token = gcp.rest(ic.IAMCredentialsClient).generate_id_token(request={"name": f"projects/-/serviceAccounts/{sa}", "audience": "https://facilities.example.com", "include_email": True}).token
open("sa_token.txt", "w").write(token)
print("service account", sa, "-> ID token is a JWT:", token.count(".") == 2)
