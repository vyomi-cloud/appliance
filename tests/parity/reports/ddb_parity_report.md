# DynamoDB differential parity — Vyomi core vs DynamoDB Local

- oracle: `amazon/dynamodb-local @ http://127.0.0.1:8123`  
- generated: 2026-10-30T09:37:16Z  
- core: `core/dynamodb_core.py` + `core/dynamodb_expr.py` (InMemoryNoSqlStore)

## Summary

| suite | total | exact | alias | message-only | mismatch | oracle-gap | parity % | semantic % |
|---|---|---|---|---|---|---|---|---|
| hand-written cases | 154 | 139 | 10 | 0 | 3 | 2 | 98.0 | 98.0 |
| hand-written steps (responses) | 663 | 648 | 10 | 0 | 3 | 2 | 99.5 | 99.5 |
| random sequences (400 × 30 ops) | 400 | 400 | – | – | 0 | – | 100.0 | – |
| random-sequence steps | 12800 | 12800 | – | – | 0 | – | 100.0 | – |

*exact* = identical normalised status + body. *alias* = identical except an error wording/code where DynamoDB Local is known to differ from the real service and the core keeps the real wording (see `ORACLE_WORDING`). *message-only* = same status and error `__type`, different human-readable message. *oracle-gap* = DynamoDB Local does not implement the operation (excluded from %). Normalisation drops request ids, timestamps, ItemCount/TableSizeBytes (eventually consistent in real DynamoDB), ARN region/account, set/scan/batch ordering and numeric spelling (`1.50` ≡ `1.5`); it never hides a value difference.

## By area

| area | cases | matching |
|---|---|---|
| batch | 8 | 8 |
| conditions | 12 | 12 |
| crud | 1 | 1 |
| expr | 2 | 2 |
| index | 9 | 8 |
| legacy | 1 | 1 |
| limits | 2 | 2 |
| numbers | 4 | 4 |
| partiql | 15 | 15 |
| query | 14 | 14 |
| returnvalues | 8 | 8 |
| scan | 6 | 6 |
| table | 10 | 9 |
| transact | 6 | 6 |
| ttl | 2 | 1 |
| types | 2 | 2 |
| update | 14 | 14 |
| validation | 38 | 36 |

## Non-exact hand-written cases

### `create_duplicate_table` — alias (table)
- **CreateTable** (alias)
  - request: `{"AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST", "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "TableName": "par_t1"}`
  - core:   `{"body": {"__type": "ResourceInUseException", "message": "Table already exists: par_t1"}, "status": 400}`
  - oracle: `{"body": {"__type": "ResourceInUseException", "message": "Cannot create preexisting table"}, "status": 400}`
  - diff: $.body.message: core="Table already exists: par_t1" oracle="Cannot create preexisting table"

### `describe_missing_table` — alias (table)
- **DescribeTable** (alias)
  - request: `{"TableName": "par_nope"}`
  - core:   `{"body": {"__type": "ResourceNotFoundException", "message": "Requested resource not found: Table: par_nope not found"}, "status": 400}`
  - oracle: `{"body": {"__type": "ResourceNotFoundException", "message": "Cannot do operations on a non-existent table"}, "status": 400}`
  - diff: $.body.message: core="Requested resource not found: Table: par_nope not found" oracle="Cannot do operations on a non-existent table"

### `delete_table_then_describe` — alias (table)
- **DescribeTable** (alias)
  - request: `{"TableName": "par_t1"}`
  - core:   `{"body": {"__type": "ResourceNotFoundException", "message": "Requested resource not found: Table: par_t1 not found"}, "status": 400}`
  - oracle: `{"body": {"__type": "ResourceNotFoundException", "message": "Cannot do operations on a non-existent table"}, "status": 400}`
  - diff: $.body.message: core="Requested resource not found: Table: par_t1 not found" oracle="Cannot do operations on a non-existent table"

### `ttl_expired_item_still_readable` — mismatch (ttl)
- **GetItem** (mismatch)
  - request: `{"Key": {"pk": {"S": "a"}}, "TableName": "par_t1"}`
  - core:   `{"body": {}, "status": 200}`
  - oracle: `{"body": {"Item": {"exp": {"N": "1000"}, "pk": {"S": "a"}}}, "status": 200}`
  - diff: $.body.Item: missing in core (oracle={"exp": {"N": "1000"}, "pk": {"S": "a"}})

### `tags_roundtrip` — oracle-gap (table)
- **ListTagsOfResource** (oracle-gap)
  - request: `{"ResourceArn": "arn:aws:dynamodb:us-east-1:000000000000:table/par_t1"}`
  - core:   `{"body": {"Tags": [{"Key": "env", "Value": "dev"}]}, "status": 200}`
  - oracle: `{"body": {"__type": "UnknownOperationException", "message": "Tagging is not currently supported in DynamoDB Local."}, "status": 400}`
  - diff: $.body.Tags: extra in core (core=[{"Key": "env", "Value": "dev"}])
  - diff: $.body.__type: missing in core (oracle="UnknownOperationException")
  - diff: $.body.message: missing in core (oracle="Tagging is not currently supported in DynamoDB Local.")
  - diff: $.status: core=200 oracle=400

### `batch_write_missing_table` — alias (batch)
- **BatchWriteItem** (alias)
  - request: `{"RequestItems": {"par_nope": [{"PutRequest": {"Item": {"pk": {"S": "a"}}}}]}}`
  - core:   `{"body": {"__type": "ResourceNotFoundException", "message": "Requested resource not found: Table: par_nope not found"}, "status": 400}`
  - oracle: `{"body": {"__type": "ResourceNotFoundException", "message": "Cannot do operations on a non-existent table"}, "status": 400}`
  - diff: $.body.message: core="Requested resource not found: Table: par_nope not found" oracle="Cannot do operations on a non-existent table"

### `batch_get_missing_table` — alias (batch)
- **BatchGetItem** (alias)
  - request: `{"RequestItems": {"par_nope": {"Keys": [{"pk": {"S": "a"}}]}}}`
  - core:   `{"body": {"__type": "ResourceNotFoundException", "message": "Requested resource not found: Table: par_nope not found"}, "status": 400}`
  - oracle: `{"body": {"__type": "ResourceNotFoundException", "message": "Cannot do operations on a non-existent table"}, "status": 400}`
  - diff: $.body.message: core="Requested resource not found: Table: par_nope not found" oracle="Cannot do operations on a non-existent table"

### `transact_write_missing_table` — alias (transact)
- **TransactWriteItems** (alias)
  - request: `{"TransactItems": [{"Put": {"Item": {"pk": {"S": "a"}}, "TableName": "par_nope"}}]}`
  - core:   `{"body": {"__type": "ResourceNotFoundException", "message": "Requested resource not found: Table: par_nope not found"}, "status": 400}`
  - oracle: `{"body": {"__type": "ResourceNotFoundException", "message": "Cannot do operations on a non-existent table"}, "status": 400}`
  - diff: $.body.message: core="Requested resource not found: Table: par_nope not found" oracle="Cannot do operations on a non-existent table"

### `get_key_wrong_type` — alias (validation)
- **GetItem** (alias)
  - request: `{"Key": {"pk": {"N": "1"}}, "TableName": "par_t1"}`
  - core:   `{"body": {"__type": "ValidationException", "message": "The provided key element does not match the schema"}, "status": 400}`
  - oracle: `{"body": {"__type": "ValidationException", "message": "One or more parameter values were invalid: Type mismatch for key"}, "status": 400}`
  - diff: $.body.message: core="The provided key element does not match the schema" oracle="One or more parameter values were invalid: Type mismatch for key"

### `update_table_add_gsi_then_query` — oracle-gap (index)
- **Query** (oracle-gap)
  - request: `{"ExpressionAttributeValues": {":v": {"N": "3"}}, "IndexName": "byV", "KeyConditionExpression": "v = :v", "TableName": "par_t1"}`
  - core:   `{"body": {"Count": 1, "Items": [{"pk": {"S": "k3"}, "v": {"N": "3"}}], "ScannedCount": 1}, "status": 200}`
  - oracle: `{"body": {"__type": "InternalFailure", "message": "The request processing has failed because of an unknown error, exception or failure."}, "status": 500}`
  - diff: $.body.Count: extra in core (core=1)
  - diff: $.body.Items: extra in core (core=[{"pk": {"S": "k3"}, "v": {"N": "3"}}])
  - diff: $.body.ScannedCount: extra in core (core=1)
  - diff: $.body.__type: missing in core (oracle="InternalFailure")
  - diff: $.body.message: missing in core (oracle="The request processing has failed because of an unknown error, exception or failure.")
  - diff: $.status: core=200 oracle=500

### `create_table_missing_attrdef` — alias (validation)
- **CreateTable** (alias)
  - request: `{"AttributeDefinitions": [{"AttributeName": "other", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST", "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "TableName": "par_t1"}`
  - core:   `{"body": {"__type": "ValidationException", "message": "One or more parameter values were invalid: Some index key attributes are not defined in AttributeDefinitions. Keys: [pk], AttributeDefinitions: [other]"}, "status": 400}`
  - oracle: `{"body": {"__type": "ValidationException", "message": "Hash Key not specified in Attribute Definitions.  Type unknown."}, "status": 400}`
  - diff: $.body.message: core="One or more parameter values were invalid: Some index key attributes are not defined in AttributeDefinitions. Keys: [pk], AttributeDefinitions: [other]" oracle="Hash Key not specified in Attribute Definitions.  Type unknown."

### `partiql_insert_duplicate` — alias (partiql)
- **ExecuteStatement** (alias)
  - request: `{"Statement": "INSERT INTO \"par_t2\" VALUE {'pk': 'a', 'sk': '1'}"}`
  - core:   `{"body": {"__type": "DuplicateItemException", "message": "Duplicate primary key exists in table"}, "status": 400}`
  - oracle: `{"body": {"__type": "DuplicateItem", "message": "Duplicate primary key exists in table"}, "status": 400}`
  - diff: $.body.__type: core="DuplicateItemException" oracle="DuplicateItem"

### `partiql_missing_table` — alias (partiql)
- **ExecuteStatement** (alias)
  - request: `{"Statement": "SELECT * FROM \"par_nope\""}`
  - core:   `{"body": {"__type": "ResourceNotFoundException", "message": "Requested resource not found: Table: par_nope not found"}, "status": 400}`
  - oracle: `{"body": {"__type": "ResourceNotFoundException", "message": "Cannot do operations on a non-existent table"}, "status": 400}`
  - diff: $.body.message: core="Requested resource not found: Table: par_nope not found" oracle="Cannot do operations on a non-existent table"

### `create_table_short_name` — mismatch (validation)
- **CreateTable** (mismatch)
  - request: `{"AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}], "BillingMode": "PAY_PER_REQUEST", "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "TableName": "ab"}`
  - core:   `{"body": {"TableDescription": {"AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}], "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"}, "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "ProvisionedThroughput": {"ReadCapacityUnits": 0, "WriteCapacityUnits": 0}, "TableArn": "arn:aws:dynamodb:REGION:ACCOUNT:table/ab", "TableName": "ab", "TableStatus": "ACTIVE"}}, "status": 200}`
  - oracle: `{"body": {"__type": "ValidationException", "message": "Invalid table/index name.  Table/index names must be between 3 and 255 characters long, and may contain only the characters a-z, A-Z, 0-9, '_', '-', and '.'"}, "status": 400}`
  - diff: $.body.TableDescription: extra in core (core={"TableName": "ab", "TableArn": "arn:aws:dynamodb:REGION:ACCOUNT:table/ab", "TableStatus": "ACTIVE", "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], )
  - diff: $.body.__type: missing in core (oracle="ValidationException")
  - diff: $.body.message: missing in core (oracle="Invalid table/index name.  Table/index names must be between 3 and 255 characters long, and may contain only the characters a-z, A-Z, 0-9, '_', '-', and '.'")
  - diff: $.status: core=200 oracle=400

### `create_table_implicit_provisioned` — mismatch (validation)
- **CreateTable** (mismatch)
  - request: `{"AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}], "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "TableName": "par_t1"}`
  - core:   `{"body": {"TableDescription": {"AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}], "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"}, "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}], "ProvisionedThroughput": {"ReadCapacityUnits": 0, "WriteCapacityUnits": 0}, "TableArn": "arn:aws:dynamodb:REGION:ACCOUNT:table/par_t1", "TableName": "par_t1", "TableStatus": "ACTIVE"}}, "status": 200}`
  - oracle: `{"body": {"__type": "ValidationException", "message": "No provisioned throughput specified for the table"}, "status": 400}`
  - diff: $.body.TableDescription: extra in core (core={"TableName": "par_t1", "TableArn": "arn:aws:dynamodb:REGION:ACCOUNT:table/par_t1", "TableStatus": "ACTIVE", "KeySchema": [{"AttributeName": "pk", "KeyType": "H)
  - diff: $.body.__type: missing in core (oracle="ValidationException")
  - diff: $.body.message: missing in core (oracle="No provisioned throughput specified for the table")
  - diff: $.status: core=200 oracle=400

