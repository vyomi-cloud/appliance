import boto3, sys, json
EP="http://127.0.0.1:18741"
def cli(svc, ak="test", sk="test"):
    return boto3.client(svc, endpoint_url=EP, region_name="us-east-1", aws_access_key_id=ak, aws_secret_access_key=sk)
iam=cli("iam")
u=sys.argv[1]
try: iam.create_user(UserName=u)
except Exception as e: print("cu",e)
k=iam.create_access_key(UserName=u)["AccessKey"]
print(json.dumps({"ak":k["AccessKeyId"],"sk":k["SecretAccessKey"]}))
