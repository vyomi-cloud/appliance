"""Capture REAL /api/iam/<cloud>/events payloads from the appliance app into $TMPDIR/events-fixture.json (input of smoke-iam-events.mjs).
   PYTHONPATH=$PWD:$PWD/core python3 consoles/tests/iam-events-fixture.py"""
import os,sys,json,tempfile,uuid
sys.path[:0]=[os.getcwd(),os.getcwd()+"/core"]
os.environ["CLOUDLEARN_TIER_ENFORCE"]="0"
os.environ["CLOUDLEARN_STATE_FILE"]=os.path.join(tempfile.mkdtemp(),"s.sqlite3")
from urllib.parse import urlencode
from fastapi.testclient import TestClient
import server
from core import gcp_project
c=TestClient(server.app); PID=gcp_project.DEFAULT_PROJECT_ID
A="AWS4-HMAC-SHA256 Credential=AKIATEST/20260101/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=x"
trust=json.dumps({"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]})
c.post("/",content=urlencode(dict(Action="CreateRole",RoleName="smokeRole",AssumeRolePolicyDocument=trust,Version="2010-05-08")),headers={"authorization":A,"content-type":"application/x-www-form-urlencoded"})
c.post(f"/v1/projects/{PID}/serviceAccounts",headers={"X-Cloudlearn-Principal":"user:ops@example.com"},json={"accountId":"smokesa","serviceAccount":{}})
SUB="/subscriptions/00000000-0000-0000-0000-cloudlearn01"
c.put(SUB+"/resourceGroups/rgs?api-version=2021-04-01",json={"location":"eastus"})
c.put(SUB+"/resourceGroups/rgs/providers/Microsoft.Authorization/roleAssignments/"+str(uuid.uuid4())+"?api-version=2022-04-01",json={"properties":{"principalId":"p1","roleDefinitionId":SUB+"/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"}})
out={k:c.get(f"/api/iam/{k}/events").json() for k in ("aws","gcp","azure")}
print({k:len(v["events"]) for k,v in out.items()})
json.dump(out,open(os.environ["TMPDIR"]+"/events-fixture.json","w"))
