import boto3

ddb = boto3.client("dynamodb")
for name, key in (("facilities-assets", "asset_id"), ("facilities-work-orders", "work_order_id"), ("approval-ledger", "request_id")):
    try:
        ddb.create_table(TableName=name, KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                         AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        print("created", name)
    except ddb.exceptions.ResourceInUseException:
        print("exists ", name)
