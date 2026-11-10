// Real aws-sdk-go-v2 ApiGatewayV2 conformance against Vyomi — only BaseEndpoint is overridden.
// One [PASS]/[FAIL] line per check; non-zero exit on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/apigatewayv2"
	"github.com/aws/aws-sdk-go-v2/service/apigatewayv2/types"
)

var pass, fail int

func chk(name string, ok bool, detail string) bool {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
	} else {
		fail++
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	}
	return ok
}

func must(name string, err error) bool {
	if err != nil {
		return chk(name, false, err.Error())
	}
	return chk(name, true, "")
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	c := apigatewayv2.NewFromConfig(cfg, func(o *apigatewayv2.Options) { o.BaseEndpoint = aws.String(ep) })
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%100000)

	api, err := c.CreateApi(ctx, &apigatewayv2.CreateApiInput{
		Name: aws.String("go-http-" + sfx), ProtocolType: types.ProtocolTypeHttp, Description: aws.String("conformance"),
		Tags: map[string]string{"env": "test"}})
	if !must("CreateApi (HTTP)", err) {
		os.Exit(1)
	}
	id := api.ApiId
	chk("CreateApi returns apiEndpoint + id", api.ApiEndpoint != nil && id != nil && len(*id) > 0, fmt.Sprint(api.ApiEndpoint))
	g, err := c.GetApi(ctx, &apigatewayv2.GetApiInput{ApiId: id})
	chk("GetApi", err == nil && *g.Name == "go-http-"+sfx && g.Tags["env"] == "test", fmt.Sprint(err))
	l, err := c.GetApis(ctx, &apigatewayv2.GetApisInput{})
	found := false
	if err == nil {
		for _, a := range l.Items {
			if *a.ApiId == *id {
				found = true
			}
		}
	}
	chk("GetApis lists the API", found, fmt.Sprint(err))
	u, err := c.UpdateApi(ctx, &apigatewayv2.UpdateApiInput{ApiId: id, Name: aws.String("go-renamed-" + sfx),
		CorsConfiguration: &types.Cors{AllowOrigins: []string{"*"}, AllowMethods: []string{"GET"}}})
	chk("UpdateApi (name + CORS)", err == nil && *u.Name == "go-renamed-"+sfx && u.CorsConfiguration != nil, fmt.Sprint(err))

	_, err = c.GetApi(ctx, &apigatewayv2.GetApiInput{ApiId: aws.String("doesnotexist")})
	var nf *types.NotFoundException
	chk("GetApi unknown → NotFoundException", errors.As(err, &nf), fmt.Sprint(err))
	_, err = c.CreateApi(ctx, &apigatewayv2.CreateApiInput{Name: aws.String("x"), ProtocolType: types.ProtocolTypeWebsocket})
	var br *types.BadRequestException
	chk("CreateApi WEBSOCKET without routeSelectionExpression → BadRequestException", errors.As(err, &br), fmt.Sprint(err))

	integ, err := c.CreateIntegration(ctx, &apigatewayv2.CreateIntegrationInput{ApiId: id,
		IntegrationType: types.IntegrationTypeHttpProxy, IntegrationUri: aws.String("https://example.com"),
		IntegrationMethod: aws.String("GET"), PayloadFormatVersion: aws.String("1.0")})
	if !must("CreateIntegration (HTTP_PROXY)", err) {
		os.Exit(1)
	}
	iid := integ.IntegrationId
	gi, err := c.GetIntegration(ctx, &apigatewayv2.GetIntegrationInput{ApiId: id, IntegrationId: iid})
	chk("GetIntegration", err == nil && *gi.IntegrationUri == "https://example.com", fmt.Sprint(err))
	ui, err := c.UpdateIntegration(ctx, &apigatewayv2.UpdateIntegrationInput{ApiId: id, IntegrationId: iid, TimeoutInMillis: aws.Int32(12000)})
	chk("UpdateIntegration", err == nil && *ui.TimeoutInMillis == 12000, fmt.Sprint(err))

	route, err := c.CreateRoute(ctx, &apigatewayv2.CreateRouteInput{ApiId: id, RouteKey: aws.String("GET /items/{id}"),
		Target: aws.String("integrations/" + *iid)})
	if !must("CreateRoute", err) {
		os.Exit(1)
	}
	rid := route.RouteId
	rs, err := c.GetRoutes(ctx, &apigatewayv2.GetRoutesInput{ApiId: id})
	chk("GetRoutes", err == nil && len(rs.Items) == 1 && *rs.Items[0].RouteKey == "GET /items/{id}", fmt.Sprint(err))
	ur, err := c.UpdateRoute(ctx, &apigatewayv2.UpdateRouteInput{ApiId: id, RouteId: rid, OperationName: aws.String("getItem")})
	chk("UpdateRoute", err == nil && *ur.OperationName == "getItem", fmt.Sprint(err))
	_, err = c.CreateRoute(ctx, &apigatewayv2.CreateRouteInput{ApiId: id, RouteKey: aws.String("GET /items/{id}")})
	var cf *types.ConflictException
	chk("CreateRoute duplicate key → ConflictException", errors.As(err, &cf), fmt.Sprint(err))
	_, err = c.CreateRouteResponse(ctx, &apigatewayv2.CreateRouteResponseInput{ApiId: id, RouteId: rid, RouteResponseKey: aws.String("$default")})
	must("CreateRouteResponse", err)

	az, err := c.CreateAuthorizer(ctx, &apigatewayv2.CreateAuthorizerInput{ApiId: id, Name: aws.String("jwt"),
		AuthorizerType: types.AuthorizerTypeJwt, IdentitySource: []string{"$request.header.Authorization"},
		JwtConfiguration: &types.JWTConfiguration{Audience: []string{"aud"}, Issuer: aws.String("https://issuer.example.com")}})
	chk("CreateAuthorizer (JWT)", err == nil && az.AuthorizerId != nil, fmt.Sprint(err))
	_, err = c.CreateModel(ctx, &apigatewayv2.CreateModelInput{ApiId: id, Name: aws.String("Item"), Schema: aws.String(`{"type":"object"}`)})
	must("CreateModel", err)

	_, err = c.CreateStage(ctx, &apigatewayv2.CreateStageInput{ApiId: id, StageName: aws.String("prod"),
		StageVariables: map[string]string{"k": "v"}})
	must("CreateStage", err)
	dep, err := c.CreateDeployment(ctx, &apigatewayv2.CreateDeploymentInput{ApiId: id, StageName: aws.String("prod"), Description: aws.String("v1")})
	chk("CreateDeployment DEPLOYED", err == nil && dep.DeploymentStatus == types.DeploymentStatusDeployed, fmt.Sprint(err))
	st, err := c.GetStage(ctx, &apigatewayv2.GetStageInput{ApiId: id, StageName: aws.String("prod")})
	chk("Stage points at the deployment", err == nil && dep != nil && *st.DeploymentId == *dep.DeploymentId && st.StageVariables["k"] == "v", fmt.Sprint(err))
	_, err = c.CreateStage(ctx, &apigatewayv2.CreateStageInput{ApiId: id, StageName: aws.String("prod")})
	chk("CreateStage duplicate → ConflictException", errors.As(err, &cf), fmt.Sprint(err))
	us, err := c.UpdateStage(ctx, &apigatewayv2.UpdateStageInput{ApiId: id, StageName: aws.String("prod"), Description: aws.String("prod stage")})
	chk("UpdateStage", err == nil && *us.Description == "prod stage", fmt.Sprint(err))

	arn := "arn:aws:apigateway:us-east-1::/apis/" + *id
	_, err = c.TagResource(ctx, &apigatewayv2.TagResourceInput{ResourceArn: aws.String(arn), Tags: map[string]string{"team": "x"}})
	must("TagResource", err)
	tg, err := c.GetTags(ctx, &apigatewayv2.GetTagsInput{ResourceArn: aws.String(arn)})
	chk("GetTags", err == nil && tg.Tags["team"] == "x", fmt.Sprint(err))
	_, err = c.UntagResource(ctx, &apigatewayv2.UntagResourceInput{ResourceArn: aws.String(arn), TagKeys: []string{"team"}})
	tg, err2 := c.GetTags(ctx, &apigatewayv2.GetTagsInput{ResourceArn: aws.String(arn)})
	chk("UntagResource", err == nil && err2 == nil && tg.Tags["team"] == "" && tg.Tags["env"] == "test", fmt.Sprint(err, err2))

	dom := "go-" + sfx + ".example.com"
	_, err = c.CreateDomainName(ctx, &apigatewayv2.CreateDomainNameInput{DomainName: aws.String(dom)})
	must("CreateDomainName", err)
	m, err := c.CreateApiMapping(ctx, &apigatewayv2.CreateApiMappingInput{DomainName: aws.String(dom), ApiId: id, Stage: aws.String("prod")})
	chk("CreateApiMapping", err == nil && m.ApiMappingId != nil, fmt.Sprint(err))
	_, err = c.DeleteDomainName(ctx, &apigatewayv2.DeleteDomainNameInput{DomainName: aws.String(dom)})
	must("DeleteDomainName", err)

	vl, err := c.CreateVpcLink(ctx, &apigatewayv2.CreateVpcLinkInput{Name: aws.String("vl-" + sfx), SubnetIds: []string{"subnet-12345"}})
	if must("CreateVpcLink", err) {
		g, err := c.GetVpcLink(ctx, &apigatewayv2.GetVpcLinkInput{VpcLinkId: vl.VpcLinkId})
		chk("GetVpcLink AVAILABLE", err == nil && g.VpcLinkStatus == types.VpcLinkStatusAvailable, fmt.Sprint(err))
		_, err = c.DeleteVpcLink(ctx, &apigatewayv2.DeleteVpcLinkInput{VpcLinkId: vl.VpcLinkId})
		must("DeleteVpcLink", err)
	}

	q, err := c.CreateApi(ctx, &apigatewayv2.CreateApiInput{Name: aws.String("go-quick-" + sfx), ProtocolType: types.ProtocolTypeHttp, Target: aws.String("https://example.com")})
	if must("CreateApi quick-create (target)", err) {
		rs, err := c.GetRoutes(ctx, &apigatewayv2.GetRoutesInput{ApiId: q.ApiId})
		chk("Quick-create made one $default route", err == nil && len(rs.Items) == 1 && *rs.Items[0].RouteKey == "$default", fmt.Sprint(err))
		_, err = c.DeleteApi(ctx, &apigatewayv2.DeleteApiInput{ApiId: q.ApiId})
		must("DeleteApi (quick-create)", err)
	}

	_, err = c.DeleteRoute(ctx, &apigatewayv2.DeleteRouteInput{ApiId: id, RouteId: rid})
	must("DeleteRoute", err)
	_, err = c.DeleteIntegration(ctx, &apigatewayv2.DeleteIntegrationInput{ApiId: id, IntegrationId: iid})
	must("DeleteIntegration", err)
	_, err = c.DeleteStage(ctx, &apigatewayv2.DeleteStageInput{ApiId: id, StageName: aws.String("prod")})
	must("DeleteStage", err)
	_, err = c.DeleteApi(ctx, &apigatewayv2.DeleteApiInput{ApiId: id})
	must("DeleteApi", err)
	_, err = c.GetApi(ctx, &apigatewayv2.GetApiInput{ApiId: id})
	chk("GetApi after delete → NotFoundException", errors.As(err, &nf), fmt.Sprint(err))

	fmt.Printf("\n%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
