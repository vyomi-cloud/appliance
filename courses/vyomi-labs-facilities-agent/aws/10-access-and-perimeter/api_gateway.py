import boto3

ag, cg, waf = boto3.client("apigateway"), boto3.client("cognito-idp"), boto3.client("wafv2")
REGION, ACCOUNT = "us-east-1", "123456789012"
pool = next(p["Id"] for p in cg.list_user_pools(MaxResults=20)["UserPools"] if p["Name"] == "facilities-users")
acl = next(a["ARN"] for a in waf.list_web_acls(Scope="REGIONAL")["WebACLs"] if a["Name"] == "facilities-acl")
fn = "arn:aws:lambda:%s:%s:function:facilities-kb-search" % (REGION, ACCOUNT)

api = ag.create_rest_api(name="facilities-api")["id"]
root = next(r["id"] for r in ag.get_resources(restApiId=api)["items"] if r["path"] == "/")
res = ag.create_resource(restApiId=api, parentId=root, pathPart="search")["id"]
auth = ag.create_authorizer(restApiId=api, name="cognito", type="COGNITO_USER_POOLS", identitySource="method.request.header.Authorization",
                            providerARNs=["arn:aws:cognito-idp:%s:%s:userpool/%s" % (REGION, ACCOUNT, pool)])["id"]
ag.put_method(restApiId=api, resourceId=res, httpMethod="POST", authorizationType="COGNITO_USER_POOLS", authorizerId=auth)
ag.put_integration(restApiId=api, resourceId=res, httpMethod="POST", type="AWS_PROXY", integrationHttpMethod="POST",
                   uri="arn:aws:apigateway:%s:lambda:path/2015-03-31/functions/%s/invocations" % (REGION, fn))
ag.create_deployment(restApiId=api, stageName="prod")
waf.associate_web_acl(WebACLArn=acl, ResourceArn="arn:aws:apigateway:%s::/restapis/%s/stages/prod" % (REGION, api))
print("api", api, "stage prod, Cognito authorizer, WAF attached")
