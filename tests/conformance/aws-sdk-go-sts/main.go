// Real aws-sdk-go-v2 STS conformance against the Vyomi appliance: unmodified
// sts.Client, only BaseEndpoint changed.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
//
// One [PASS]/[FAIL] line per check; non-zero exit on any failure.
package main

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/sts"
	"github.com/aws/aws-sdk-go-v2/service/sts/types"
	"github.com/aws/smithy-go"
)

var pass, fail int

func chk(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fail++
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func client(ep string, creds aws.CredentialsProvider) *sts.Client {
	return sts.New(sts.Options{Region: "us-east-1", BaseEndpoint: aws.String(ep), Credentials: creds})
}

func code(err error) string {
	var ae smithy.APIError
	if errors.As(err, &ae) {
		return ae.ErrorCode()
	}
	return fmt.Sprint(err)
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	c := client(ep, credentials.NewStaticCredentialsProvider("test", "test", ""))
	roleArn := "arn:aws:iam::123456789012:role/go-sts-role"

	id, err := c.GetCallerIdentity(ctx, &sts.GetCallerIdentityInput{})
	chk("GetCallerIdentity returns the account root", err == nil && aws.ToString(id.Account) == "123456789012" &&
		strings.HasSuffix(aws.ToString(id.Arn), ":root"), fmt.Sprint(err))

	ar, err := c.AssumeRole(ctx, &sts.AssumeRoleInput{RoleArn: aws.String(roleArn), RoleSessionName: aws.String("go-session"),
		DurationSeconds: aws.Int32(1800), ExternalId: aws.String("ext-go")})
	if err != nil {
		chk("AssumeRole returns temporary credentials", false, err.Error())
	} else {
		cr := ar.Credentials
		chk("AssumeRole returns temporary credentials", strings.HasPrefix(aws.ToString(cr.AccessKeyId), "ASIA") &&
			aws.ToString(cr.SessionToken) != "" && cr.Expiration.After(time.Now()), aws.ToString(cr.AccessKeyId))
		want := "arn:aws:sts::123456789012:assumed-role/go-sts-role/go-session"
		chk("AssumeRole AssumedRoleUser ARN is assumed-role/<role>/<session>", aws.ToString(ar.AssumedRoleUser.Arn) == want,
			aws.ToString(ar.AssumedRoleUser.Arn))
		c2 := client(ep, credentials.NewStaticCredentialsProvider(aws.ToString(cr.AccessKeyId), aws.ToString(cr.SecretAccessKey), aws.ToString(cr.SessionToken)))
		id2, err := c2.GetCallerIdentity(ctx, &sts.GetCallerIdentityInput{})
		chk("GetCallerIdentity with the temporary credentials reports the assumed role", err == nil && aws.ToString(id2.Arn) == want,
			fmt.Sprint(err))
		ki, err := c.GetAccessKeyInfo(ctx, &sts.GetAccessKeyInfoInput{AccessKeyId: cr.AccessKeyId})
		chk("GetAccessKeyInfo returns the owning account", err == nil && aws.ToString(ki.Account) == "123456789012", fmt.Sprint(err))
	}

	st, err := c.GetSessionToken(ctx, &sts.GetSessionTokenInput{DurationSeconds: aws.Int32(3600)})
	chk("GetSessionToken returns credentials", err == nil && strings.HasPrefix(aws.ToString(st.Credentials.AccessKeyId), "ASIA"), fmt.Sprint(err))

	ft, err := c.GetFederationToken(ctx, &sts.GetFederationTokenInput{Name: aws.String("go-fed")})
	chk("GetFederationToken returns the federated user", err == nil &&
		aws.ToString(ft.FederatedUser.Arn) == "arn:aws:sts::123456789012:federated-user/go-fed", fmt.Sprint(err))

	jwt := "e30." + base64.RawURLEncoding.EncodeToString([]byte(`{"sub":"user-go","aud":"app","iss":"https://idp.example.com"}`)) + ".sig"
	wi, err := c.AssumeRoleWithWebIdentity(ctx, &sts.AssumeRoleWithWebIdentityInput{RoleArn: aws.String(roleArn),
		RoleSessionName: aws.String("web-go"), WebIdentityToken: aws.String(jwt)})
	chk("AssumeRoleWithWebIdentity returns the token subject", err == nil && aws.ToString(wi.SubjectFromWebIdentityToken) == "user-go", fmt.Sprint(err))

	dm, err := c.DecodeAuthorizationMessage(ctx, &sts.DecodeAuthorizationMessageInput{
		EncodedMessage: aws.String(base64.StdEncoding.EncodeToString([]byte(`{"allowed":false}`)))})
	chk("DecodeAuthorizationMessage decodes the message", err == nil && strings.Contains(aws.ToString(dm.DecodedMessage), "allowed"), fmt.Sprint(err))

	_, err = c.AssumeRole(ctx, &sts.AssumeRoleInput{RoleArn: aws.String(roleArn), RoleSessionName: aws.String("x y!")})
	chk("AssumeRole rejects an invalid session name", err != nil && code(err) == "ValidationError", fmt.Sprint(err))

	_, err = c.AssumeRole(ctx, &sts.AssumeRoleInput{RoleArn: aws.String(roleArn), RoleSessionName: aws.String("ok-name"), Policy: aws.String("{not json")})
	var mp *types.MalformedPolicyDocumentException
	chk("AssumeRole rejects a malformed policy", errors.As(err, &mp), fmt.Sprint(err))

	_, err = c.DecodeAuthorizationMessage(ctx, &sts.DecodeAuthorizationMessageInput{EncodedMessage: aws.String("!!notbase64!!")})
	var ia *types.InvalidAuthorizationMessageException
	chk("DecodeAuthorizationMessage rejects garbage", errors.As(err, &ia), fmt.Sprint(err))

	fmt.Printf("== %d passed, %d failed ==\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
