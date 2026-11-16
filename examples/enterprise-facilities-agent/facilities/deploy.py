"""Provisioning helpers: deploy the tool Lambdas (real zip + CreateFunction), create tables. Plain boto3."""
import io, json, os, zipfile
from .runtime import NAMES

HERE = os.path.join(os.path.dirname(__file__), "lambdas")
FIX = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


def zip_of(module):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(HERE, module + ".py"), module + ".py")
    return b.getvalue()


def deploy_lambda(ctx, name, module, env):
    lam = ctx.client("lambda")
    env = dict(env, AWS_ENDPOINT_URL=ctx.endpoint, AWS_DEFAULT_REGION=ctx.region)   # standard SDK env vars, how a function targets a non-default endpoint
    try:
        lam.get_function(FunctionName=name)
        lam.update_function_code(FunctionName=name, ZipFile=zip_of(module))
        lam.update_function_configuration(FunctionName=name, Environment={"Variables": env})
    except lam.exceptions.ResourceNotFoundException:
        lam.create_function(FunctionName=name, Runtime="python3.12", Role=NAMES["role"], Handler=f"{module}.handler",
                            Code={"ZipFile": zip_of(module)}, Timeout=30, Environment={"Variables": env})
    return f"arn:aws:lambda:{ctx.region}:123456789012:function:{name}"


def make_table(ctx, name, key):
    ddb = ctx.client("dynamodb")
    try:
        ddb.create_table(TableName=name, KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                         AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
    except ddb.exceptions.ResourceInUseException:
        pass


def seed(ctx, table, rows):
    def attr(v):
        return {"N": str(v)} if isinstance(v, (int, float)) else {"S": str(v)}
    for r in rows:
        ctx.client("dynamodb").put_item(TableName=table, Item={k: attr(v) for k, v in r.items()})


def fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


def lambda_env(ctx):
    return dict(KB_ID=ctx.state.get("kb_id", ""), ASSETS_TABLE=NAMES["assets"], WORK_ORDERS_TABLE=NAMES["work_orders"],
                LEDGER_TABLE=NAMES["ledger"], INBOX_TOPIC_ARN=ctx.state.get("topic_arn", ""))
