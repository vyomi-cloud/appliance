import boto3

cg = boto3.client("cognito-idp")
USER, PW = "maria.ops@example.com", "Fac!lities-2026"
pool = cg.create_user_pool(PoolName="facilities-users")["UserPool"]["Id"]
cid = cg.create_user_pool_client(UserPoolId=pool, ClientName="facilities-web",
                                 ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]["ClientId"]
cg.admin_create_user(UserPoolId=pool, Username=USER, UserAttributes=[{"Name": "email", "Value": USER}], MessageAction="SUPPRESS")
cg.admin_set_user_password(UserPoolId=pool, Username=USER, Password=PW, Permanent=True)
auth = cg.initiate_auth(ClientId=cid, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": USER, "PASSWORD": PW})["AuthenticationResult"]
print("signed in as", cg.get_user(AccessToken=auth["AccessToken"])["Username"])
print("id token is a JWT:", auth["IdToken"].count(".") == 2, "(%d chars)" % len(auth["IdToken"]))
