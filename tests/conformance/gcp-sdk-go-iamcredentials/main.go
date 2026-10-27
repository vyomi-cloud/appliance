// Real cloud.google.com/go/iam/credentials (REST transport) conformance against Vyomi's IAM
// Service Account Credentials API. ENDPOINT (default http://127.0.0.1:9000), PROJECT. One
// [PASS]/[FAIL] line per check; exits non-zero on any failure.
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	credentials "cloud.google.com/go/iam/credentials/apiv1"
	"cloud.google.com/go/iam/credentials/apiv1/credentialspb"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/option"
	"google.golang.org/protobuf/types/known/durationpb"
)

var pass, fail int

func check(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
	} else {
		fail++
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	}
}

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func httpCode(err error) int {
	var ge *googleapi.Error
	if errors.As(err, &ge) {
		return ge.Code
	}
	return 0
}

func claims(tok string) map[string]interface{} {
	parts := strings.Split(tok, ".")
	if len(parts) != 3 {
		return nil
	}
	b, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil
	}
	m := map[string]interface{}{}
	_ = json.Unmarshal(b, &m)
	return m
}

func header(tok string) map[string]interface{} {
	b, err := base64.RawURLEncoding.DecodeString(strings.Split(tok, ".")[0])
	if err != nil {
		return nil
	}
	m := map[string]interface{}{}
	_ = json.Unmarshal(b, &m)
	return m
}

func httpDo(method, url string, body interface{}) (int, []byte) {
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, _ := http.NewRequest(method, url, rd)
	req.Header.Set("content-type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, []byte(err.Error())
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, b
}

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	project := env("PROJECT", "go-iamc-proj")
	suffix := fmt.Sprintf("%d", time.Now().Unix()%1000000)
	fmt.Printf("== cloud.google.com/go/iam/credentials (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	// Service accounts come from the IAM API (a separate service) — create the two we use.
	mk := func(id string) string {
		code, _ := httpDo("POST", fmt.Sprintf("%s/v1/projects/%s/serviceAccounts", endpoint, project), map[string]string{"accountId": id})
		check("IAM: create service account "+id, code == 200 || code == 409, fmt.Sprint(code))
		return fmt.Sprintf("projects/-/serviceAccounts/%s@%s.iam.gserviceaccount.com", id, project)
	}
	sa := mk("go-sa-" + suffix)
	delegate := mk("go-del-" + suffix)

	c, err := credentials.NewIamCredentialsRESTClient(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	defer c.Close()

	scope := []string{"https://www.googleapis.com/auth/cloud-platform"}
	if r, err := c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: sa, Scope: scope}); err != nil {
		check("GenerateAccessToken", false, err.Error())
	} else {
		d := time.Until(r.ExpireTime.AsTime())
		check("GenerateAccessToken (ya29 token, ~1h expiry)", strings.HasPrefix(r.AccessToken, "ya29.") && d > 55*time.Minute && d <= 61*time.Minute, fmt.Sprint(r.AccessToken[:6], d))
	}

	if r, err := c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: sa, Scope: scope, Lifetime: durationpb.New(10 * time.Minute)}); err != nil {
		check("GenerateAccessToken with lifetime", false, err.Error())
	} else {
		d := time.Until(r.ExpireTime.AsTime())
		check("GenerateAccessToken lifetime honoured (10m)", d > 9*time.Minute && d <= 11*time.Minute, d.String())
	}

	if r, err := c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: sa, Scope: scope, Delegates: []string{delegate}}); err != nil {
		check("GenerateAccessToken with delegate chain", false, err.Error())
	} else {
		check("GenerateAccessToken with delegate chain", r.AccessToken != "", "")
	}

	_, err = c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: sa})
	check("GenerateAccessToken without scope -> 400", httpCode(err) == 400, fmt.Sprint(err))
	_, err = c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: sa, Scope: scope, Lifetime: durationpb.New(24 * time.Hour)})
	check("GenerateAccessToken lifetime > 12h -> 400", httpCode(err) == 400, fmt.Sprint(err))
	_, err = c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: "projects/-/serviceAccounts/ghost-" + suffix + "@" + project + ".iam.gserviceaccount.com", Scope: scope})
	check("unknown service account -> 403 PERMISSION_DENIED", httpCode(err) == 403, fmt.Sprint(err))
	_, err = c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: strings.Replace(sa, "projects/-", "projects/"+project, 1), Scope: scope})
	check("project other than '-' -> 400", httpCode(err) == 400, fmt.Sprint(err))
	_, err = c.GenerateAccessToken(ctx, &credentialspb.GenerateAccessTokenRequest{Name: sa, Scope: scope, Delegates: []string{"projects/-/serviceAccounts/ghost-" + suffix + "@" + project + ".iam.gserviceaccount.com"}})
	check("unknown delegate -> 403", httpCode(err) == 403, fmt.Sprint(err))

	if r, err := c.GenerateIdToken(ctx, &credentialspb.GenerateIdTokenRequest{Name: sa, Audience: "https://svc.example.com", IncludeEmail: true}); err != nil {
		check("GenerateIdToken", false, err.Error())
	} else {
		cl, h := claims(r.Token), header(r.Token)
		check("GenerateIdToken (RS256 JWT, aud + email claims)", cl != nil && cl["aud"] == "https://svc.example.com" &&
			strings.HasPrefix(fmt.Sprint(cl["email"]), "go-sa-") && h["alg"] == "RS256" && cl["iss"] == "https://accounts.google.com", r.Token)
	}
	_, err = c.GenerateIdToken(ctx, &credentialspb.GenerateIdTokenRequest{Name: sa})
	check("GenerateIdToken without audience -> 400", httpCode(err) == 400, fmt.Sprint(err))

	blob := []byte("sign these bytes")
	if r, err := c.SignBlob(ctx, &credentialspb.SignBlobRequest{Name: sa, Payload: blob}); err != nil {
		check("SignBlob", false, err.Error())
	} else {
		check("SignBlob (2048-bit signature + 40-hex key id)", len(r.SignedBlob) == 256 && len(r.KeyId) == 40, fmt.Sprint(len(r.SignedBlob), r.KeyId))
		r2, _ := c.SignBlob(ctx, &credentialspb.SignBlobRequest{Name: sa, Payload: blob})
		check("SignBlob is deterministic per account", r2 != nil && bytes.Equal(r.SignedBlob, r2.SignedBlob) && r.KeyId == r2.KeyId, "")
	}

	payload := fmt.Sprintf(`{"iss":"%s","aud":"https://example.com","exp":%d}`, strings.TrimPrefix(sa, "projects/-/serviceAccounts/"), time.Now().Add(time.Hour).Unix())
	if r, err := c.SignJwt(ctx, &credentialspb.SignJwtRequest{Name: sa, Payload: payload}); err != nil {
		check("SignJwt", false, err.Error())
	} else {
		cl, h := claims(r.SignedJwt), header(r.SignedJwt)
		check("SignJwt (claims preserved, kid = keyId)", cl != nil && cl["aud"] == "https://example.com" && h["kid"] == r.KeyId, r.SignedJwt)
	}
	_, err = c.SignJwt(ctx, &credentialspb.SignJwtRequest{Name: sa, Payload: "not json"})
	check("SignJwt with a non-JSON payload -> 400", httpCode(err) == 400, fmt.Sprint(err))

	code, body := httpDo("GET", endpoint+"/api/gcp/iamcredentials/credentials", nil)
	check("console lists the issued credentials (no secrets)", code == 200 && strings.Contains(string(body), "go-sa-"+suffix) && !strings.Contains(string(body), "ya29."), fmt.Sprint(code))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
