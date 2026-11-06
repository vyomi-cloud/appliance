"""Cognito IDP (user pools) core conformance — host CPython + Pyodide (Nano).

Drives the native JSON-1.1 wire (`AWSCognitoIdentityProviderService.<Op>`) through
core.cognito_idp_core.dispatch: pool/client/group/domain lifecycles, sign-up and
confirmation, admin user management, password policy, USER_PASSWORD_AUTH, the
NEW_PASSWORD_REQUIRED challenge, refresh, GlobalSignOut revocation, forgot-password,
ListUsers filters, pagination, error codes, and RS256 token verification via JWKS.
"""
import base64
import json

try:
    from core import cognito_idp_core as cg
except ImportError:  # pragma: no cover - Pyodide flat layout
    import cognito_idp_core as cg  # type: ignore

PFX = "AWSCognitoIdentityProviderService."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or cg.InMemoryCognitoIdpStore()

    def call(op, **p):
        r = cg.dispatch(s, PFX + op, p)
        return r.status, r.body

    def ok(op, **p):
        st, b = call(op, **p)
        _check(f"{op} -> 200", st == 200 and "__type" not in b)
        return b

    def err(op, code, **p):
        st, b = call(op, **p)
        _check(f"{op} -> {code}", st == 400 and b.get("__type") == code)
        return b

    pool = ok("CreateUserPool", PoolName="app-users", AutoVerifiedAttributes=["email"],
              Schema=[{"Name": "tenant", "AttributeDataType": "String", "Mutable": True}])["UserPool"]
    pid = pool["Id"]
    _check("pool id shape", pid.startswith("us-east-1_") and len(pid) == 19)
    _check("pool arn", pool["Arn"].endswith(":userpool/" + pid))
    _check("custom attribute in schema", any(a["Name"] == "custom:tenant" for a in pool["SchemaAttributes"]))
    _check("describe pool", ok("DescribeUserPool", UserPoolId=pid)["UserPool"]["Name"] == "app-users")
    err("DescribeUserPool", "ResourceNotFoundException", UserPoolId="us-east-1_nope")
    err("ListUserPools", "InvalidParameterException")  # MaxResults required
    _check("list pools", [x["Id"] for x in ok("ListUserPools", MaxResults=10)["UserPools"]] == [pid])
    ok("UpdateUserPool", UserPoolId=pid, MfaConfiguration="OFF", UserPoolTags={"env": "dev"})
    _check("tags via arn", ok("ListTagsForResource", ResourceArn=pool["Arn"])["Tags"] == {"env": "dev"})
    ok("TagResource", ResourceArn=pool["Arn"], Tags={"team": "x"})
    ok("UntagResource", ResourceArn=pool["Arn"], TagKeys=["env"])
    _check("untag", ok("ListTagsForResource", ResourceArn=pool["Arn"])["Tags"] == {"team": "x"})
    ok("AddCustomAttributes", UserPoolId=pid, CustomAttributes=[{"Name": "plan", "AttributeDataType": "String"}])

    cl = ok("CreateUserPoolClient", UserPoolId=pid, ClientName="web", GenerateSecret=False,
            ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_ADMIN_USER_PASSWORD_AUTH"])["UserPoolClient"]
    cid = cl["ClientId"]
    _check("client id shape", len(cid) == 26)
    dflt = ok("CreateUserPoolClient", UserPoolId=pid, ClientName="default-flows")["UserPoolClient"]
    err("InitiateAuth", "InvalidParameterException", AuthFlow="USER_PASSWORD_AUTH", ClientId=dflt["ClientId"],
        AuthParameters={"USERNAME": "x", "PASSWORD": "y"})
    sec = ok("CreateUserPoolClient", UserPoolId=pid, ClientName="srv", GenerateSecret=True,
             ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH"])["UserPoolClient"]
    _check("client secret generated", bool(sec.get("ClientSecret")))
    _check("list clients", len(ok("ListUserPoolClients", UserPoolId=pid, MaxResults=10)["UserPoolClients"]) == 3)
    ok("UpdateUserPoolClient", UserPoolId=pid, ClientId=cid, ClientName="web2")
    _check("describe client", ok("DescribeUserPoolClient", UserPoolId=pid, ClientId=cid)["UserPoolClient"]["ClientName"] == "web2")

    # sign-up / confirm / sign-in
    su = ok("SignUp", ClientId=cid, Username="alice", Password="Passw0rd!x",
            UserAttributes=[{"Name": "email", "Value": "alice@example.com"}])
    _check("signup unconfirmed", su["UserConfirmed"] is False and su["CodeDeliveryDetails"]["DeliveryMedium"] == "EMAIL")
    err("SignUp", "UsernameExistsException", ClientId=cid, Username="alice", Password="Passw0rd!x")
    err("SignUp", "InvalidPasswordException", ClientId=cid, Username="bob", Password="alllowercase1!")
    err("SignUp", "NotAuthorizedException", ClientId=sec["ClientId"], Username="carol", Password="Passw0rd!x")
    err("InitiateAuth", "UserNotConfirmedException", AuthFlow="USER_PASSWORD_AUTH", ClientId=cid,
        AuthParameters={"USERNAME": "alice", "PASSWORD": "Passw0rd!x"})
    err("ConfirmSignUp", "CodeMismatchException", ClientId=cid, Username="alice", ConfirmationCode="000000")
    ok("ConfirmSignUp", ClientId=cid, Username="alice", ConfirmationCode="123456")
    err("InitiateAuth", "NotAuthorizedException", AuthFlow="USER_PASSWORD_AUTH", ClientId=cid,
        AuthParameters={"USERNAME": "alice", "PASSWORD": "wrong"})
    err("InitiateAuth", "UserNotFoundException", AuthFlow="USER_PASSWORD_AUTH", ClientId=cid,
        AuthParameters={"USERNAME": "ghost", "PASSWORD": "Passw0rd!x"})
    auth = ok("InitiateAuth", AuthFlow="USER_PASSWORD_AUTH", ClientId=cid,
              AuthParameters={"USERNAME": "alice", "PASSWORD": "Passw0rd!x"})["AuthenticationResult"]
    _check("tokens issued", all(auth.get(k) for k in ("AccessToken", "IdToken", "RefreshToken")) and auth["TokenType"] == "Bearer")
    idc = json.loads(base64.urlsafe_b64decode(auth["IdToken"].split(".")[1] + "=="))
    _check("id token claims", idc["token_use"] == "id" and idc["aud"] == cid and idc["email"] == "alice@example.com"
           and idc["email_verified"] is True and idc["iss"].endswith(pid))
    # RS256 signature verifies against the published JWKS
    k = cg.jwks(s, pid)["keys"][0]
    n = int.from_bytes(base64.urlsafe_b64decode(k["n"] + "=="), "big")
    h, pl, sg = auth["IdToken"].split(".")
    _check("JWKS verifies RS256 signature", cg._jwt_verify(auth["IdToken"])["sub"] == idc["sub"] and k["kid"] and n == cg._RSA_N)
    gu = ok("GetUser", AccessToken=auth["AccessToken"])
    _check("get user", gu["Username"] == "alice" and {"Name": "email", "Value": "alice@example.com"} in gu["UserAttributes"])
    ok("UpdateUserAttributes", AccessToken=auth["AccessToken"], UserAttributes=[{"Name": "custom:tenant", "Value": "t1"}])
    _check("attribute updated", {"Name": "custom:tenant", "Value": "t1"} in ok("GetUser", AccessToken=auth["AccessToken"])["UserAttributes"])
    err("UpdateUserAttributes", "InvalidParameterException", AccessToken=auth["AccessToken"], UserAttributes=[{"Name": "sub", "Value": "x"}])
    ref = ok("InitiateAuth", AuthFlow="REFRESH_TOKEN_AUTH", ClientId=cid, AuthParameters={"REFRESH_TOKEN": auth["RefreshToken"]})
    _check("refresh returns new access+id, no new refresh token", ref["AuthenticationResult"].get("AccessToken") and "RefreshToken" not in ref["AuthenticationResult"])
    ok("ChangePassword", AccessToken=auth["AccessToken"], PreviousPassword="Passw0rd!x", ProposedPassword="N3wPassw0rd!")
    err("ChangePassword", "NotAuthorizedException", AccessToken=auth["AccessToken"], PreviousPassword="bad", ProposedPassword="N3wPassw0rd!")
    ok("GlobalSignOut", AccessToken=auth["AccessToken"])
    err("GetUser", "NotAuthorizedException", AccessToken=auth["AccessToken"])
    err("InitiateAuth", "NotAuthorizedException", AuthFlow="REFRESH_TOKEN_AUTH", ClientId=cid, AuthParameters={"REFRESH_TOKEN": auth["RefreshToken"]})
    err("GetUser", "NotAuthorizedException", AccessToken="not.a.jwt")

    # forgot password
    ok("ForgotPassword", ClientId=cid, Username="alice")
    err("ConfirmForgotPassword", "CodeMismatchException", ClientId=cid, Username="alice", ConfirmationCode="1", Password="Another1!pw")
    ok("ConfirmForgotPassword", ClientId=cid, Username="alice", ConfirmationCode="123456", Password="Another1!pw")
    ok("InitiateAuth", AuthFlow="USER_PASSWORD_AUTH", ClientId=cid, AuthParameters={"USERNAME": "alice", "PASSWORD": "Another1!pw"})

    # admin user management + challenge
    u = ok("AdminCreateUser", UserPoolId=pid, Username="dave", TemporaryPassword="Temp#Pass1",
           UserAttributes=[{"Name": "email", "Value": "dave@example.com"}, {"Name": "email_verified", "Value": "true"}])["User"]
    _check("admin-created user FORCE_CHANGE_PASSWORD", u["UserStatus"] == "FORCE_CHANGE_PASSWORD" and u["Enabled"])
    err("AdminCreateUser", "UsernameExistsException", UserPoolId=pid, Username="dave")
    ch = ok("AdminInitiateAuth", UserPoolId=pid, ClientId=cid, AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": "dave", "PASSWORD": "Temp#Pass1"})
    _check("NEW_PASSWORD_REQUIRED challenge", ch["ChallengeName"] == "NEW_PASSWORD_REQUIRED" and ch["Session"])
    err("AdminRespondToAuthChallenge", "InvalidPasswordException", UserPoolId=pid, ClientId=cid, ChallengeName="NEW_PASSWORD_REQUIRED",
        Session=ch["Session"], ChallengeResponses={"USERNAME": "dave", "NEW_PASSWORD": "weakweak1!"})
    done = ok("AdminRespondToAuthChallenge", UserPoolId=pid, ClientId=cid, ChallengeName="NEW_PASSWORD_REQUIRED",
              Session=ch["Session"], ChallengeResponses={"USERNAME": "dave", "NEW_PASSWORD": "Perm#anent9"})
    _check("challenge completes with tokens", "AccessToken" in done["AuthenticationResult"])
    _check("admin get user CONFIRMED", ok("AdminGetUser", UserPoolId=pid, Username="dave")["UserStatus"] == "CONFIRMED")
    ok("AdminDisableUser", UserPoolId=pid, Username="dave")
    err("AdminInitiateAuth", "NotAuthorizedException", UserPoolId=pid, ClientId=cid, AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": "dave", "PASSWORD": "Perm#anent9"})
    ok("AdminEnableUser", UserPoolId=pid, Username="dave")
    ok("AdminSetUserPassword", UserPoolId=pid, Username="dave", Password="Reset#Pass1", Permanent=True)
    ok("AdminUpdateUserAttributes", UserPoolId=pid, Username="dave", UserAttributes=[{"Name": "given_name", "Value": "Dave"}])
    ok("AdminDeleteUserAttributes", UserPoolId=pid, Username="dave", UserAttributeNames=["given_name"])
    ok("AdminResetUserPassword", UserPoolId=pid, Username="dave")
    err("AdminInitiateAuth", "PasswordResetRequiredException", UserPoolId=pid, ClientId=cid, AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": "dave", "PASSWORD": "Reset#Pass1"})

    # groups
    ok("CreateGroup", UserPoolId=pid, GroupName="admins", Description="Admins", Precedence=1)
    err("CreateGroup", "GroupExistsException", UserPoolId=pid, GroupName="admins")
    ok("AdminAddUserToGroup", UserPoolId=pid, Username="alice", GroupName="admins")
    _check("groups for user", [g["GroupName"] for g in ok("AdminListGroupsForUser", UserPoolId=pid, Username="alice")["Groups"]] == ["admins"])
    _check("users in group", [x["Username"] for x in ok("ListUsersInGroup", UserPoolId=pid, GroupName="admins")["Users"]] == ["alice"])
    tok = ok("InitiateAuth", AuthFlow="USER_PASSWORD_AUTH", ClientId=cid, AuthParameters={"USERNAME": "alice", "PASSWORD": "Another1!pw"})["AuthenticationResult"]
    _check("cognito:groups claim", json.loads(base64.urlsafe_b64decode(tok["AccessToken"].split(".")[1] + "=="))["cognito:groups"] == ["admins"])
    ok("UpdateGroup", UserPoolId=pid, GroupName="admins", Description="Administrators")
    _check("get group", ok("GetGroup", UserPoolId=pid, GroupName="admins")["Group"]["Description"] == "Administrators")
    ok("AdminRemoveUserFromGroup", UserPoolId=pid, Username="alice", GroupName="admins")
    ok("DeleteGroup", UserPoolId=pid, GroupName="admins")
    err("GetGroup", "ResourceNotFoundException", UserPoolId=pid, GroupName="admins")

    # list users / filter / pagination
    for i in range(5):
        ok("AdminCreateUser", UserPoolId=pid, Username=f"user{i}", UserAttributes=[{"Name": "email", "Value": f"u{i}@x.io"}])
    allu = ok("ListUsers", UserPoolId=pid)["Users"]
    _check("list users", len(allu) == 7)
    _check("filter =", [x["Username"] for x in ok("ListUsers", UserPoolId=pid, Filter='email = "u3@x.io"')["Users"]] == ["user3"])
    _check("filter ^=", len(ok("ListUsers", UserPoolId=pid, Filter='username ^= "user"')["Users"]) == 5)
    pg = ok("ListUsers", UserPoolId=pid, Limit=3)
    _check("pagination token", len(pg["Users"]) == 3 and pg["PaginationToken"])
    pg2 = ok("ListUsers", UserPoolId=pid, Limit=3, PaginationToken=pg["PaginationToken"])
    _check("page 2", len(pg2["Users"]) == 3)
    err("ListUsers", "InvalidParameterException", UserPoolId=pid, Filter="garbage")

    # domain / idp / resource server
    ok("CreateUserPoolDomain", UserPoolId=pid, Domain="my-app-auth")
    _check("describe domain", ok("DescribeUserPoolDomain", Domain="my-app-auth")["DomainDescription"]["UserPoolId"] == pid)
    err("CreateUserPoolDomain", "InvalidParameterException", UserPoolId=pid, Domain="other")
    ok("DeleteUserPoolDomain", UserPoolId=pid, Domain="my-app-auth")
    ok("CreateIdentityProvider", UserPoolId=pid, ProviderName="Goog", ProviderType="Google",
       ProviderDetails={"client_id": "a", "client_secret": "b", "authorize_scopes": "email"})
    err("CreateIdentityProvider", "DuplicateProviderException", UserPoolId=pid, ProviderName="Goog", ProviderType="Google")
    _check("list idps", ok("ListIdentityProviders", UserPoolId=pid, MaxResults=10)["Providers"][0]["ProviderName"] == "Goog")
    ok("DeleteIdentityProvider", UserPoolId=pid, ProviderName="Goog")
    ok("CreateResourceServer", UserPoolId=pid, Identifier="https://api.x.io", Name="api", Scopes=[{"ScopeName": "read", "ScopeDescription": "r"}])
    _check("list resource servers", len(ok("ListResourceServers", UserPoolId=pid, MaxResults=10)["ResourceServers"]) == 1)
    ok("DeleteResourceServer", UserPoolId=pid, Identifier="https://api.x.io")

    # email-as-username pool
    ep = ok("CreateUserPool", PoolName="email-pool", UsernameAttributes=["email"], Policies={"PasswordPolicy": {"MinimumLength": 8, "RequireSymbols": False}})["UserPool"]
    ec = ok("CreateUserPoolClient", UserPoolId=ep["Id"], ClientName="c", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH"])["UserPoolClient"]
    ok("SignUp", ClientId=ec["ClientId"], Username="eve@example.com", Password="NoSymbols1")
    err("SignUp", "InvalidParameterException", ClientId=ec["ClientId"], Username="notanemail", Password="NoSymbols1")
    ok("AdminConfirmSignUp", UserPoolId=ep["Id"], Username="eve@example.com")
    a = ok("InitiateAuth", AuthFlow="USER_PASSWORD_AUTH", ClientId=ec["ClientId"], AuthParameters={"USERNAME": "eve@example.com", "PASSWORD": "NoSymbols1"})
    gu = ok("GetUser", AccessToken=a["AuthenticationResult"]["AccessToken"])
    _check("email pool: Username is the sub", len(gu["Username"]) == 36)
    ok("DeleteUser", AccessToken=a["AuthenticationResult"]["AccessToken"])
    err("AdminGetUser", "UserNotFoundException", UserPoolId=ep["Id"], Username="eve@example.com")

    # cleanup + deletion protection
    ok("AdminDeleteUser", UserPoolId=pid, Username="alice")
    ok("DeleteUserPoolClient", UserPoolId=pid, ClientId=cid)
    err("DescribeUserPoolClient", "ResourceNotFoundException", UserPoolId=pid, ClientId=cid)
    ok("UpdateUserPool", UserPoolId=pid, DeletionProtection="ACTIVE")
    err("DeleteUserPool", "InvalidParameterException", UserPoolId=pid)
    ok("UpdateUserPool", UserPoolId=pid, DeletionProtection="INACTIVE")
    ok("DeleteUserPool", UserPoolId=pid)
    ok("DeleteUserPool", UserPoolId=ep["Id"])
    _check("pools gone", ok("ListUserPools", MaxResults=10)["UserPools"] == [])
    st, b = call("NoSuchThing")
    _check("unknown operation", st == 400 and "UnknownOperation" in b["__type"])
    st, b = call("CreateTerms")
    _check("model-but-unimplemented op", st == 400 and b["__type"] == "UnsupportedOperationException")
    print("cognito-idp core: all checks passed")


def test_cognito_idp_core():
    run()


if __name__ == "__main__":
    run()
