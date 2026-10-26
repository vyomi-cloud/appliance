// Amazon Cognito user pools — real aws-sdk-go-v2 against Vyomi (BaseEndpoint override only).
//
//	ENDPOINT=http://localhost:9000 GOFLAGS=-mod=mod go run .
//
// One [PASS]/[FAIL] line per check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	cip "github.com/aws/aws-sdk-go-v2/service/cognitoidentityprovider"
	"github.com/aws/aws-sdk-go-v2/service/cognitoidentityprovider/types"
)

var pass, fail int

func check(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fail++
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func must(name string, err error) bool {
	if err != nil {
		check(name, false, err.Error())
		return false
	}
	return true
}

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://localhost:9000"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] config ::", err)
		os.Exit(1)
	}
	c := cip.NewFromConfig(cfg, func(o *cip.Options) { o.BaseEndpoint = aws.String(endpoint) })
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)

	pool, err := c.CreateUserPool(ctx, &cip.CreateUserPoolInput{PoolName: aws.String("go-pool-" + sfx),
		AutoVerifiedAttributes: []types.VerifiedAttributeType{types.VerifiedAttributeTypeEmail},
		UsernameAttributes:     []types.UsernameAttributeType{types.UsernameAttributeTypeEmail}})
	if !must("CreateUserPool", err) {
		os.Exit(1)
	}
	pid := *pool.UserPool.Id
	check("CreateUserPool id/arn", strings.HasPrefix(pid, "us-east-1_") && strings.HasSuffix(*pool.UserPool.Arn, "userpool/"+pid), pid)
	d, err := c.DescribeUserPool(ctx, &cip.DescribeUserPoolInput{UserPoolId: &pid})
	if must("DescribeUserPool", err) {
		check("DescribeUserPool username attributes", len(d.UserPool.UsernameAttributes) == 1, fmt.Sprint(d.UserPool.UsernameAttributes))
	}
	l, err := c.ListUserPools(ctx, &cip.ListUserPoolsInput{MaxResults: aws.Int32(60)})
	if must("ListUserPools", err) {
		found := false
		for _, p := range l.UserPools {
			found = found || *p.Id == pid
		}
		check("ListUserPools contains pool", found, "")
	}

	cl, err := c.CreateUserPoolClient(ctx, &cip.CreateUserPoolClientInput{UserPoolId: &pid, ClientName: aws.String("go-client"), GenerateSecret: true,
		ExplicitAuthFlows: []types.ExplicitAuthFlowsType{types.ExplicitAuthFlowsTypeAllowUserPasswordAuth, types.ExplicitAuthFlowsTypeAllowRefreshTokenAuth}})
	if !must("CreateUserPoolClient", err) {
		os.Exit(1)
	}
	cid := *cl.UserPoolClient.ClientId
	check("client secret generated", cl.UserPoolClient.ClientSecret != nil && *cl.UserPoolClient.ClientSecret != "", "")

	// email-as-username pool: stored Username is the sub; secret hash required
	_, err = c.SignUp(ctx, &cip.SignUpInput{ClientId: &cid, Username: aws.String("gina@example.com"), Password: aws.String("Passw0rd!x")})
	var na *types.NotAuthorizedException
	check("SignUp without SecretHash -> NotAuthorizedException", errors.As(err, &na), fmt.Sprint(err))
	cl2, err := c.CreateUserPoolClient(ctx, &cip.CreateUserPoolClientInput{UserPoolId: &pid, ClientName: aws.String("go-public"),
		ExplicitAuthFlows: []types.ExplicitAuthFlowsType{types.ExplicitAuthFlowsTypeAllowUserPasswordAuth, types.ExplicitAuthFlowsTypeAllowRefreshTokenAuth}})
	must("CreateUserPoolClient (public)", err)
	pub := *cl2.UserPoolClient.ClientId
	su, err := c.SignUp(ctx, &cip.SignUpInput{ClientId: &pub, Username: aws.String("gina@example.com"), Password: aws.String("Passw0rd!x")})
	if must("SignUp", err) {
		check("SignUp returns sub, unconfirmed", !su.UserConfirmed && len(*su.UserSub) == 36, "")
	}
	var bad *types.InvalidParameterException
	_, err = c.SignUp(ctx, &cip.SignUpInput{ClientId: &pub, Username: aws.String("not-an-email"), Password: aws.String("Passw0rd!x")})
	check("SignUp bad username -> InvalidParameterException", errors.As(err, &bad), fmt.Sprint(err))
	_, err = c.ConfirmSignUp(ctx, &cip.ConfirmSignUpInput{ClientId: &pub, Username: aws.String("gina@example.com"), ConfirmationCode: aws.String("123456")})
	must("ConfirmSignUp", err)
	au, err := c.InitiateAuth(ctx, &cip.InitiateAuthInput{ClientId: &pub, AuthFlow: types.AuthFlowTypeUserPasswordAuth,
		AuthParameters: map[string]string{"USERNAME": "gina@example.com", "PASSWORD": "Passw0rd!x"}})
	if must("InitiateAuth USER_PASSWORD_AUTH", err) {
		r := au.AuthenticationResult
		check("tokens issued", len(strings.Split(*r.AccessToken, ".")) == 3 && len(strings.Split(*r.IdToken, ".")) == 3 && r.RefreshToken != nil, "")
		g, err := c.GetUser(ctx, &cip.GetUserInput{AccessToken: r.AccessToken})
		if must("GetUser", err) {
			email := ""
			for _, a := range g.UserAttributes {
				if *a.Name == "email" {
					email = *a.Value
				}
			}
			check("GetUser email attribute", email == "gina@example.com" && len(*g.Username) == 36, *g.Username)
		}
		_, err = c.GlobalSignOut(ctx, &cip.GlobalSignOutInput{AccessToken: r.AccessToken})
		must("GlobalSignOut", err)
		_, err = c.GetUser(ctx, &cip.GetUserInput{AccessToken: r.AccessToken})
		check("GetUser after sign-out -> NotAuthorizedException", errors.As(err, &na), fmt.Sprint(err))
	}

	// admin lifecycle + groups + listing
	_, err = c.AdminCreateUser(ctx, &cip.AdminCreateUserInput{UserPoolId: &pid, Username: aws.String("hank@example.com"),
		TemporaryPassword: aws.String("Temp#Pass1"), UserAttributes: []types.AttributeType{{Name: aws.String("email"), Value: aws.String("hank@example.com")}}})
	must("AdminCreateUser", err)
	_, err = c.AdminSetUserPassword(ctx, &cip.AdminSetUserPasswordInput{UserPoolId: &pid, Username: aws.String("hank@example.com"), Password: aws.String("Perm#anent9"), Permanent: true})
	must("AdminSetUserPassword", err)
	_, err = c.CreateGroup(ctx, &cip.CreateGroupInput{UserPoolId: &pid, GroupName: aws.String("ops"), Description: aws.String("Operators"), Precedence: aws.Int32(5)})
	must("CreateGroup", err)
	users, err := c.ListUsers(ctx, &cip.ListUsersInput{UserPoolId: &pid})
	if must("ListUsers", err) {
		check("ListUsers returns both users", len(users.Users) == 2, fmt.Sprint(len(users.Users)))
		hank := ""
		for _, u := range users.Users {
			for _, a := range u.Attributes {
				if *a.Name == "email" && *a.Value == "hank@example.com" {
					hank = *u.Username
				}
			}
		}
		_, err = c.AdminAddUserToGroup(ctx, &cip.AdminAddUserToGroupInput{UserPoolId: &pid, Username: &hank, GroupName: aws.String("ops")})
		must("AdminAddUserToGroup", err)
		gs, err := c.AdminListGroupsForUser(ctx, &cip.AdminListGroupsForUserInput{UserPoolId: &pid, Username: &hank})
		if must("AdminListGroupsForUser", err) {
			check("group membership", len(gs.Groups) == 1 && *gs.Groups[0].GroupName == "ops", "")
		}
		gu, err := c.AdminGetUser(ctx, &cip.AdminGetUserInput{UserPoolId: &pid, Username: aws.String("hank@example.com")})
		if must("AdminGetUser by email alias", err) {
			check("AdminGetUser status", gu.UserStatus == types.UserStatusTypeConfirmed, string(gu.UserStatus))
		}
	}
	_, err = c.CreateUserPoolDomain(ctx, &cip.CreateUserPoolDomainInput{UserPoolId: &pid, Domain: aws.String("go-auth-" + sfx)})
	must("CreateUserPoolDomain", err)
	dd, err := c.DescribeUserPoolDomain(ctx, &cip.DescribeUserPoolDomainInput{Domain: aws.String("go-auth-" + sfx)})
	if must("DescribeUserPoolDomain", err) {
		check("domain belongs to pool", *dd.DomainDescription.UserPoolId == pid, "")
	}
	_, err = c.DeleteUserPoolDomain(ctx, &cip.DeleteUserPoolDomainInput{UserPoolId: &pid, Domain: aws.String("go-auth-" + sfx)})
	must("DeleteUserPoolDomain", err)
	var nf *types.ResourceNotFoundException
	_, err = c.DescribeUserPool(ctx, &cip.DescribeUserPoolInput{UserPoolId: aws.String("us-east-1_doesnotexist")})
	check("DescribeUserPool unknown -> ResourceNotFoundException", errors.As(err, &nf), fmt.Sprint(err))
	_, err = c.DeleteUserPool(ctx, &cip.DeleteUserPoolInput{UserPoolId: &pid})
	must("DeleteUserPool", err)
	l2, _ := c.ListUserPools(ctx, &cip.ListUserPoolsInput{MaxResults: aws.Int32(60)})
	gone := true
	for _, p := range l2.UserPools {
		gone = gone && *p.Id != pid
	}
	check("pool gone after delete", gone, "")

	fmt.Printf("%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
