// Real aws-sdk-go-v2 Systems Manager conformance against Vyomi — only BaseEndpoint is overridden.
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
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	"github.com/aws/aws-sdk-go-v2/service/ssm/types"
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
	c := ssm.NewFromConfig(cfg, func(o *ssm.Options) { o.BaseEndpoint = aws.String(ep) })
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)
	p := "/go-" + sfx + "/app"

	// ── Parameter Store ──
	put, err := c.PutParameter(ctx, &ssm.PutParameterInput{Name: aws.String(p + "/db/host"), Value: aws.String("db.local"),
		Type: types.ParameterTypeString, Description: aws.String("conformance"),
		Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("test")}}})
	if !must("PutParameter", err) {
		os.Exit(1)
	}
	chk("PutParameter returns Version 1 / Standard tier", put.Version == 1 && put.Tier == types.ParameterTierStandard, fmt.Sprint(put.Version, put.Tier))
	_, err = c.PutParameter(ctx, &ssm.PutParameterInput{Name: aws.String(p + "/db/host"), Value: aws.String("x"), Type: types.ParameterTypeString})
	var exists *types.ParameterAlreadyExists
	chk("PutParameter without Overwrite → ParameterAlreadyExists", errors.As(err, &exists), fmt.Sprint(err))
	put2, err := c.PutParameter(ctx, &ssm.PutParameterInput{Name: aws.String(p + "/db/host"), Value: aws.String("db2.local"), Type: types.ParameterTypeString, Overwrite: aws.Bool(true)})
	must("PutParameter Overwrite", err)
	chk("Overwrite bumps the version to 2", err == nil && put2.Version == 2, fmt.Sprint(put2))
	get, err := c.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(p + "/db/host")})
	if must("GetParameter", err) {
		chk("GetParameter value/version/ARN", aws.ToString(get.Parameter.Value) == "db2.local" && get.Parameter.Version == 2 &&
			aws.ToString(get.Parameter.ARN) == "arn:aws:ssm:us-east-1:000000000000:parameter"+p+"/db/host", fmt.Sprint(get.Parameter))
	}
	v1, err := c.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(p + "/db/host:1")})
	chk("GetParameter by version selector", err == nil && aws.ToString(v1.Parameter.Value) == "db.local", fmt.Sprint(err))
	_, err = c.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String("/nope-" + sfx)})
	var nf *types.ParameterNotFound
	chk("GetParameter unknown → ParameterNotFound", errors.As(err, &nf), fmt.Sprint(err))

	_, err = c.PutParameter(ctx, &ssm.PutParameterInput{Name: aws.String(p + "/secret"), Value: aws.String("s3cr3t"), Type: types.ParameterTypeSecureString})
	must("PutParameter SecureString", err)
	enc, _ := c.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(p + "/secret")})
	dec, _ := c.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(p + "/secret"), WithDecryption: aws.Bool(true)})
	chk("SecureString hidden without WithDecryption, clear with it",
		enc != nil && dec != nil && aws.ToString(enc.Parameter.Value) != "s3cr3t" && aws.ToString(dec.Parameter.Value) == "s3cr3t", "")

	bp, err := c.GetParametersByPath(ctx, &ssm.GetParametersByPathInput{Path: aws.String(p), Recursive: aws.Bool(true)})
	chk("GetParametersByPath recursive", err == nil && len(bp.Parameters) == 2, fmt.Sprint(err))
	gp, err := c.GetParameters(ctx, &ssm.GetParametersInput{Names: []string{p + "/db/host", "/missing-" + sfx}})
	chk("GetParameters splits InvalidParameters", err == nil && len(gp.Parameters) == 1 && len(gp.InvalidParameters) == 1, fmt.Sprint(err))
	dp, err := c.DescribeParameters(ctx, &ssm.DescribeParametersInput{ParameterFilters: []types.ParameterStringFilter{
		{Key: aws.String("Name"), Option: aws.String("BeginsWith"), Values: []string{p}}}, MaxResults: aws.Int32(1)})
	chk("DescribeParameters paginates (MaxResults=1 → NextToken)", err == nil && len(dp.Parameters) == 1 && dp.NextToken != nil, fmt.Sprint(err))
	lab, err := c.LabelParameterVersion(ctx, &ssm.LabelParameterVersionInput{Name: aws.String(p + "/db/host"), ParameterVersion: aws.Int64(1), Labels: []string{"stable"}})
	chk("LabelParameterVersion", err == nil && len(lab.InvalidLabels) == 0, fmt.Sprint(err))
	bl, err := c.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(p + "/db/host:stable")})
	chk("GetParameter by label", err == nil && bl.Parameter.Version == 1, fmt.Sprint(err))
	h, err := c.GetParameterHistory(ctx, &ssm.GetParameterHistoryInput{Name: aws.String(p + "/db/host")})
	chk("GetParameterHistory has both versions", err == nil && len(h.Parameters) == 2 && len(h.Parameters[0].Labels) == 1, fmt.Sprint(err))
	_, err = c.AddTagsToResource(ctx, &ssm.AddTagsToResourceInput{ResourceType: types.ResourceTypeForTaggingParameter, ResourceId: aws.String(p + "/db/host"),
		Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("x")}}})
	must("AddTagsToResource", err)
	tl, err := c.ListTagsForResource(ctx, &ssm.ListTagsForResourceInput{ResourceType: types.ResourceTypeForTaggingParameter, ResourceId: aws.String(p + "/db/host")})
	chk("ListTagsForResource has creation + added tags", err == nil && len(tl.TagList) == 2, fmt.Sprint(err))
	_, err = c.RemoveTagsFromResource(ctx, &ssm.RemoveTagsFromResourceInput{ResourceType: types.ResourceTypeForTaggingParameter, ResourceId: aws.String(p + "/db/host"), TagKeys: []string{"team"}})
	must("RemoveTagsFromResource", err)

	// ── Documents + Run Command ──
	doc := "go-doc-" + sfx
	cd, err := c.CreateDocument(ctx, &ssm.CreateDocumentInput{Name: aws.String(doc), DocumentType: types.DocumentTypeCommand, DocumentFormat: types.DocumentFormatJson,
		Content: aws.String(`{"schemaVersion":"2.2","description":"go","mainSteps":[]}`)})
	chk("CreateDocument", err == nil && cd.DocumentDescription.Status == types.DocumentStatusActive, fmt.Sprint(err))
	_, err = c.CreateDocument(ctx, &ssm.CreateDocumentInput{Name: aws.String(doc), Content: aws.String(`{"schemaVersion":"2.2","mainSteps":[]}`)})
	var dae *types.DocumentAlreadyExists
	chk("CreateDocument duplicate → DocumentAlreadyExists", errors.As(err, &dae), fmt.Sprint(err))
	ud, err := c.UpdateDocument(ctx, &ssm.UpdateDocumentInput{Name: aws.String(doc), DocumentVersion: aws.String("$LATEST"), Content: aws.String(`{"schemaVersion":"2.2","description":"v2","mainSteps":[]}`)})
	chk("UpdateDocument → version 2", err == nil && aws.ToString(ud.DocumentDescription.DocumentVersion) == "2", fmt.Sprint(err))
	gd, err := c.GetDocument(ctx, &ssm.GetDocumentInput{Name: aws.String(doc), DocumentVersion: aws.String("1")})
	chk("GetDocument version 1", err == nil && aws.ToString(gd.DocumentVersion) == "1", fmt.Sprint(err))
	ld, err := c.ListDocuments(ctx, &ssm.ListDocumentsInput{Filters: []types.DocumentKeyValuesFilter{{Key: aws.String("Owner"), Values: []string{"Self"}}}})
	found := false
	if err == nil {
		for _, d := range ld.DocumentIdentifiers {
			found = found || aws.ToString(d.Name) == doc
		}
	}
	chk("ListDocuments Owner=Self lists it", found, fmt.Sprint(err))
	sc, err := c.SendCommand(ctx, &ssm.SendCommandInput{DocumentName: aws.String("AWS-RunShellScript"), InstanceIds: []string{"i-0123456789abcdef0"},
		Parameters: map[string][]string{"commands": {"echo hi"}}})
	if chk("SendCommand", err == nil && sc.Command != nil, fmt.Sprint(err)) {
		inv, err := c.GetCommandInvocation(ctx, &ssm.GetCommandInvocationInput{CommandId: sc.Command.CommandId, InstanceId: aws.String("i-0123456789abcdef0")})
		chk("GetCommandInvocation → Success", err == nil && inv.Status == types.CommandInvocationStatusSuccess, fmt.Sprint(err))
	}
	_, err = c.SendCommand(ctx, &ssm.SendCommandInput{DocumentName: aws.String("no-such-doc-" + sfx), InstanceIds: []string{"i-0123456789abcdef0"}})
	var invd *types.InvalidDocument
	chk("SendCommand unknown document → InvalidDocument", errors.As(err, &invd), fmt.Sprint(err))

	// ── Maintenance windows + patch baselines ──
	mw, err := c.CreateMaintenanceWindow(ctx, &ssm.CreateMaintenanceWindowInput{Name: aws.String("go-win-" + sfx), Schedule: aws.String("cron(0 2 * * ? *)"),
		Duration: aws.Int32(4), Cutoff: 1, AllowUnassociatedTargets: false})
	if chk("CreateMaintenanceWindow", err == nil && mw.WindowId != nil, fmt.Sprint(err)) {
		gw, err := c.GetMaintenanceWindow(ctx, &ssm.GetMaintenanceWindowInput{WindowId: mw.WindowId})
		chk("GetMaintenanceWindow", err == nil && aws.ToString(gw.Name) == "go-win-"+sfx, fmt.Sprint(err))
		_, err = c.DeleteMaintenanceWindow(ctx, &ssm.DeleteMaintenanceWindowInput{WindowId: mw.WindowId})
		must("DeleteMaintenanceWindow", err)
		_, err = c.GetMaintenanceWindow(ctx, &ssm.GetMaintenanceWindowInput{WindowId: mw.WindowId})
		var dne *types.DoesNotExistException
		chk("GetMaintenanceWindow after delete → DoesNotExistException", errors.As(err, &dne), fmt.Sprint(err))
	}
	pb, err := c.CreatePatchBaseline(ctx, &ssm.CreatePatchBaselineInput{Name: aws.String("go-pb-" + sfx), OperatingSystem: types.OperatingSystemAmazonLinux2})
	if chk("CreatePatchBaseline", err == nil && pb.BaselineId != nil, fmt.Sprint(err)) {
		_, err = c.DeletePatchBaseline(ctx, &ssm.DeletePatchBaselineInput{BaselineId: pb.BaselineId})
		must("DeletePatchBaseline", err)
	}

	// ── cleanup ──
	_, err = c.DeleteDocument(ctx, &ssm.DeleteDocumentInput{Name: aws.String(doc)})
	must("DeleteDocument", err)
	_, err = c.DeleteParameter(ctx, &ssm.DeleteParameterInput{Name: aws.String(p + "/db/host")})
	must("DeleteParameter", err)
	dps, err := c.DeleteParameters(ctx, &ssm.DeleteParametersInput{Names: []string{p + "/secret", p + "/gone"}})
	chk("DeleteParameters", err == nil && len(dps.DeletedParameters) == 1 && len(dps.InvalidParameters) == 1, fmt.Sprint(err))
	_, err = c.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(p + "/db/host")})
	chk("GetParameter after delete → ParameterNotFound", errors.As(err, &nf), fmt.Sprint(err))

	fmt.Printf("\n%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
