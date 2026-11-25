import boto3, json, sys, urllib.request
from botocore.exceptions import ClientError
EP="http://127.0.0.1:18741"
def cli(svc, ak="test", sk="test"):
    return boto3.client(svc, endpoint_url=EP, region_name="us-east-1", aws_access_key_id=ak, aws_secret_access_key=sk)
def put(mode):
    r=urllib.request.Request(EP+"/api/iam/aws/enforcement",data=json.dumps({"space":mode}).encode(),method="PUT",headers={"content-type":"application/json"}); return urllib.request.urlopen(r).read()
def code(f):
    try: f(); return "OK"
    except ClientError as e: return e.response["Error"]["Code"]+" | "+e.response["Error"]["Message"][:150]
if __name__=="__main__":
    ak,sk=sys.argv[1:3]
    print(put("enforce"))
    c=lambda s: cli(s,ak,sk)
    print("s3 ListBuckets (allowed by UI-created policy):", code(lambda: c("s3").list_buckets()))
    print("sqs ListQueues (not granted):", code(lambda: c("sqs").list_queues()))
    print("s3 CreateBucket (not granted):", code(lambda: c("s3").create_bucket(Bucket="vfy-denied-bkt")))
