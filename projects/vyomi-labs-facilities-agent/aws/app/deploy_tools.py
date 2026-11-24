import io, os, zipfile
import boto3

lam = boto3.client("lambda")
ROLE = "arn:aws:iam::123456789012:role/facilities-role"
ENV = {"ASSETS_TABLE": "facilities-assets", "WORK_ORDERS_TABLE": "facilities-work-orders", "LEDGER_TABLE": "approval-ledger",
       "INBOX_TOPIC_ARN": "", "AWS_ENDPOINT_URL": os.environ["AWS_ENDPOINT_URL"], "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1")}


def zip_of(module, source):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(module + ".py", source)
    return buf.getvalue()


FUNCTIONS = (("facilities-asset-status", "asset_status"), ("facilities-request-approval", "request_approval"),
             ("facilities-create-work-order", "create_work_order"))
for name, module in FUNCTIONS:
    source = open(module + ".py").read()
    lam.create_function(FunctionName=name, Runtime="python3.12", Role=ROLE, Handler=module + ".handler",
                        Code={"ZipFile": zip_of(module, source)}, Timeout=30, Environment={"Variables": ENV})
    print("deployed", name)
