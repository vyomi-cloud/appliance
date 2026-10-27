// Real aws-sdk-go-v2 Amazon SES v2 conformance probe against Vyomi.
//
// Unmodified github.com/aws/aws-sdk-go-v2/service/sesv2 with only BaseEndpoint
// overridden. One [PASS]/[FAIL] line per check; exit 1 on failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
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
	"github.com/aws/aws-sdk-go-v2/service/sesv2"
	"github.com/aws/aws-sdk-go-v2/service/sesv2/types"
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
	if detail != "" {
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	} else {
		fmt.Printf("[FAIL] %s\n", name)
	}
}

func step(name string, err error) bool {
	if err != nil {
		chk(name, false, err.Error())
		return false
	}
	chk(name, true, "")
	return true
}

func wantErr(name, code string, err error) {
	var ae smithy.APIError
	if err == nil {
		chk(name, false, "expected "+code+" but the call succeeded")
	} else if errors.As(err, &ae) {
		chk(name, ae.ErrorCode() == code, "expected "+code+" got "+ae.ErrorCode())
	} else {
		chk(name, false, err.Error())
	}
}

func simple(subject, body string) *types.EmailContent {
	return &types.EmailContent{Simple: &types.Message{
		Subject: &types.Content{Data: aws.String(subject)},
		Body:    &types.Body{Text: &types.Content{Data: aws.String(body)}}}}
}

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx,
		config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	ses := sesv2.NewFromConfig(cfg, func(o *sesv2.Options) { o.BaseEndpoint = aws.String(endpoint) })

	sfx := fmt.Sprintf("%d", time.Now().UnixNano()/1000%1000000)
	email := "go-" + sfx + "@example.com"
	domain := "go-" + sfx + ".example.org"
	cs, tpl, list := "go-cs-"+sfx, "go-tpl-"+sfx, "go-list-"+sfx

	// identities
	ci, err := ses.CreateEmailIdentity(ctx, &sesv2.CreateEmailIdentityInput{EmailIdentity: aws.String(email)})
	if !step("CreateEmailIdentity (address)", err) {
		os.Exit(1)
	}
	chk("address identity is verified", ci.IdentityType == types.IdentityTypeEmailAddress && ci.VerifiedForSendingStatus, fmt.Sprint(ci.IdentityType))
	cd, err := ses.CreateEmailIdentity(ctx, &sesv2.CreateEmailIdentityInput{EmailIdentity: aws.String(domain)})
	step("CreateEmailIdentity (domain)", err)
	chk("domain identity has 3 DKIM tokens", err == nil && cd.DkimAttributes != nil && len(cd.DkimAttributes.Tokens) == 3, "")
	_, err = ses.CreateEmailIdentity(ctx, &sesv2.CreateEmailIdentityInput{EmailIdentity: aws.String(email)})
	wantErr("duplicate identity -> AlreadyExistsException", "AlreadyExistsException", err)
	gi, err := ses.GetEmailIdentity(ctx, &sesv2.GetEmailIdentityInput{EmailIdentity: aws.String(email)})
	step("GetEmailIdentity", err)
	chk("identity details", err == nil && gi.VerificationStatus == types.VerificationStatusSuccess, "")
	_, err = ses.GetEmailIdentity(ctx, &sesv2.GetEmailIdentityInput{EmailIdentity: aws.String("none-" + sfx + "@example.com")})
	wantErr("unknown identity -> NotFoundException", "NotFoundException", err)
	li, err := ses.ListEmailIdentities(ctx, &sesv2.ListEmailIdentitiesInput{})
	step("ListEmailIdentities", err)
	found := 0
	if err == nil {
		for _, i := range li.EmailIdentities {
			if aws.ToString(i.IdentityName) == email || aws.ToString(i.IdentityName) == domain {
				found++
			}
		}
	}
	chk("list contains both identities", found == 2, fmt.Sprint(found))
	_, err = ses.PutEmailIdentityMailFromAttributes(ctx, &sesv2.PutEmailIdentityMailFromAttributesInput{
		EmailIdentity: aws.String(domain), MailFromDomain: aws.String("mail." + domain), BehaviorOnMxFailure: types.BehaviorOnMxFailureRejectMessage})
	step("PutEmailIdentityMailFromAttributes", err)
	gd, err := ses.GetEmailIdentity(ctx, &sesv2.GetEmailIdentityInput{EmailIdentity: aws.String(domain)})
	chk("mail-from persisted", err == nil && gd.MailFromAttributes != nil && aws.ToString(gd.MailFromAttributes.MailFromDomain) == "mail."+domain, "")

	// configuration set + event destination
	_, err = ses.CreateConfigurationSet(ctx, &sesv2.CreateConfigurationSetInput{ConfigurationSetName: aws.String(cs),
		SendingOptions: &types.SendingOptions{SendingEnabled: true}})
	step("CreateConfigurationSet", err)
	gcs, err := ses.GetConfigurationSet(ctx, &sesv2.GetConfigurationSetInput{ConfigurationSetName: aws.String(cs)})
	step("GetConfigurationSet", err)
	chk("config set name", err == nil && aws.ToString(gcs.ConfigurationSetName) == cs, "")
	_, err = ses.PutConfigurationSetDeliveryOptions(ctx, &sesv2.PutConfigurationSetDeliveryOptionsInput{
		ConfigurationSetName: aws.String(cs), TlsPolicy: types.TlsPolicyRequire})
	step("PutConfigurationSetDeliveryOptions", err)
	_, err = ses.CreateConfigurationSetEventDestination(ctx, &sesv2.CreateConfigurationSetEventDestinationInput{
		ConfigurationSetName: aws.String(cs), EventDestinationName: aws.String("sns1"),
		EventDestination: &types.EventDestinationDefinition{Enabled: true,
			MatchingEventTypes: []types.EventType{types.EventTypeSend, types.EventTypeBounce},
			SnsDestination:     &types.SnsDestination{TopicArn: aws.String("arn:aws:sns:us-east-1:123456789012:t")}}})
	step("CreateConfigurationSetEventDestination", err)
	ed, err := ses.GetConfigurationSetEventDestinations(ctx, &sesv2.GetConfigurationSetEventDestinationsInput{ConfigurationSetName: aws.String(cs)})
	step("GetConfigurationSetEventDestinations", err)
	chk("event destination returned", err == nil && len(ed.EventDestinations) == 1 && len(ed.EventDestinations[0].MatchingEventTypes) == 2, "")
	lcs, err := ses.ListConfigurationSets(ctx, &sesv2.ListConfigurationSetsInput{})
	step("ListConfigurationSets", err)
	chk("config set listed", err == nil && func() bool {
		for _, n := range lcs.ConfigurationSets {
			if n == cs {
				return true
			}
		}
		return false
	}(), "")

	// templates
	_, err = ses.CreateEmailTemplate(ctx, &sesv2.CreateEmailTemplateInput{TemplateName: aws.String(tpl),
		TemplateContent: &types.EmailTemplateContent{Subject: aws.String("Hi {{name}}"), Text: aws.String("Hello {{name}}"), Html: aws.String("<b>{{name}}</b>")}})
	step("CreateEmailTemplate", err)
	tr, err := ses.TestRenderEmailTemplate(ctx, &sesv2.TestRenderEmailTemplateInput{TemplateName: aws.String(tpl), TemplateData: aws.String(`{"name":"Ada"}`)})
	step("TestRenderEmailTemplate", err)
	chk("template rendered", err == nil && strings.Contains(aws.ToString(tr.RenderedTemplate), "Subject: Hi Ada"), "")
	_, err = ses.UpdateEmailTemplate(ctx, &sesv2.UpdateEmailTemplateInput{TemplateName: aws.String(tpl),
		TemplateContent: &types.EmailTemplateContent{Subject: aws.String("Welcome {{name}}"), Text: aws.String("t")}})
	step("UpdateEmailTemplate", err)
	gt, err := ses.GetEmailTemplate(ctx, &sesv2.GetEmailTemplateInput{TemplateName: aws.String(tpl)})
	chk("template updated", err == nil && aws.ToString(gt.TemplateContent.Subject) == "Welcome {{name}}", "")
	lt, err := ses.ListEmailTemplates(ctx, &sesv2.ListEmailTemplatesInput{})
	step("ListEmailTemplates", err)
	chk("template listed", err == nil && len(lt.TemplatesMetadata) >= 1, "")

	// sending
	se, err := ses.SendEmail(ctx, &sesv2.SendEmailInput{FromEmailAddress: aws.String(email),
		Destination: &types.Destination{ToAddresses: []string{"to@example.net"}}, ConfigurationSetName: aws.String(cs),
		Content: simple("hello", "world")})
	step("SendEmail (Simple)", err)
	chk("MessageId returned", err == nil && len(aws.ToString(se.MessageId)) > 10, "")
	_, err = ses.SendEmail(ctx, &sesv2.SendEmailInput{FromEmailAddress: aws.String("anyone@" + domain),
		Destination: &types.Destination{ToAddresses: []string{"to@example.net"}},
		Content:     &types.EmailContent{Template: &types.Template{TemplateName: aws.String(tpl), TemplateData: aws.String("{}")}}})
	step("SendEmail (from a verified domain)", err)
	_, err = ses.SendEmail(ctx, &sesv2.SendEmailInput{FromEmailAddress: aws.String("x@unverified-" + sfx + ".com"),
		Destination: &types.Destination{ToAddresses: []string{"to@example.net"}}, Content: simple("a", "b")})
	wantErr("unverified sender -> MessageRejected", "MessageRejected", err)
	sb, err := ses.SendBulkEmail(ctx, &sesv2.SendBulkEmailInput{FromEmailAddress: aws.String(email),
		DefaultContent: &types.BulkEmailContent{Template: &types.Template{TemplateName: aws.String(tpl), TemplateData: aws.String("{}")}},
		BulkEmailEntries: []types.BulkEmailEntry{{Destination: &types.Destination{ToAddresses: []string{"a@example.net"}}}}})
	step("SendBulkEmail", err)
	chk("bulk entry succeeded", err == nil && len(sb.BulkEmailEntryResults) == 1 && sb.BulkEmailEntryResults[0].Status == types.BulkEmailStatusSuccess, "")

	// contact lists
	_, err = ses.CreateContactList(ctx, &sesv2.CreateContactListInput{ContactListName: aws.String(list), Description: aws.String("d"),
		Topics: []types.Topic{{TopicName: aws.String("news"), DisplayName: aws.String("News"), Description: aws.String("d"), DefaultSubscriptionStatus: types.SubscriptionStatusOptIn}}})
	step("CreateContactList", err)
	_, err = ses.CreateContact(ctx, &sesv2.CreateContactInput{ContactListName: aws.String(list), EmailAddress: aws.String("sub@example.net")})
	step("CreateContact", err)
	gc, err := ses.GetContact(ctx, &sesv2.GetContactInput{ContactListName: aws.String(list), EmailAddress: aws.String("sub@example.net")})
	step("GetContact", err)
	chk("topic default inherited", err == nil && len(gc.TopicDefaultPreferences) == 1 && gc.TopicDefaultPreferences[0].SubscriptionStatus == types.SubscriptionStatusOptIn, "")
	lc, err := ses.ListContacts(ctx, &sesv2.ListContactsInput{ContactListName: aws.String(list)})
	step("ListContacts", err)
	chk("contact listed", err == nil && len(lc.Contacts) == 1, "")

	// suppression, tags, account
	bounce := "bounce-" + sfx + "@example.net"
	_, err = ses.PutSuppressedDestination(ctx, &sesv2.PutSuppressedDestinationInput{EmailAddress: aws.String(bounce), Reason: types.SuppressionListReasonBounce})
	step("PutSuppressedDestination", err)
	gs, err := ses.GetSuppressedDestination(ctx, &sesv2.GetSuppressedDestinationInput{EmailAddress: aws.String(bounce)})
	step("GetSuppressedDestination", err)
	chk("suppression reason", err == nil && gs.SuppressedDestination.Reason == types.SuppressionListReasonBounce, "")
	_, err = ses.DeleteSuppressedDestination(ctx, &sesv2.DeleteSuppressedDestinationInput{EmailAddress: aws.String(bounce)})
	step("DeleteSuppressedDestination", err)
	arn := "arn:aws:ses:us-east-1:123456789012:identity/" + email
	_, err = ses.TagResource(ctx, &sesv2.TagResourceInput{ResourceArn: aws.String(arn),
		Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("mail")}, {Key: aws.String("env"), Value: aws.String("dev")}}})
	step("TagResource", err)
	tg, err := ses.ListTagsForResource(ctx, &sesv2.ListTagsForResourceInput{ResourceArn: aws.String(arn)})
	step("ListTagsForResource", err)
	chk("tags listed", err == nil && len(tg.Tags) == 2, "")
	_, err = ses.UntagResource(ctx, &sesv2.UntagResourceInput{ResourceArn: aws.String(arn), TagKeys: []string{"team", "env"}})
	step("UntagResource", err)
	tg, err = ses.ListTagsForResource(ctx, &sesv2.ListTagsForResourceInput{ResourceArn: aws.String(arn)})
	chk("tags removed", err == nil && len(tg.Tags) == 0, "")
	ga, err := ses.GetAccount(ctx, &sesv2.GetAccountInput{})
	step("GetAccount", err)
	chk("account quota", err == nil && ga.SendQuota != nil && ga.SendQuota.Max24HourSend > 0 && ga.SendingEnabled, "")

	// cleanup
	_, err = ses.DeleteContact(ctx, &sesv2.DeleteContactInput{ContactListName: aws.String(list), EmailAddress: aws.String("sub@example.net")})
	step("DeleteContact", err)
	_, err = ses.DeleteContactList(ctx, &sesv2.DeleteContactListInput{ContactListName: aws.String(list)})
	step("DeleteContactList", err)
	_, err = ses.DeleteEmailTemplate(ctx, &sesv2.DeleteEmailTemplateInput{TemplateName: aws.String(tpl)})
	step("DeleteEmailTemplate", err)
	_, err = ses.DeleteConfigurationSet(ctx, &sesv2.DeleteConfigurationSetInput{ConfigurationSetName: aws.String(cs)})
	step("DeleteConfigurationSet", err)
	_, err = ses.DeleteEmailIdentity(ctx, &sesv2.DeleteEmailIdentityInput{EmailIdentity: aws.String(email)})
	step("DeleteEmailIdentity (address)", err)
	_, err = ses.DeleteEmailIdentity(ctx, &sesv2.DeleteEmailIdentityInput{EmailIdentity: aws.String(domain)})
	step("DeleteEmailIdentity (domain)", err)
	_, err = ses.GetEmailIdentity(ctx, &sesv2.GetEmailIdentityInput{EmailIdentity: aws.String(email)})
	wantErr("deleted identity is gone", "NotFoundException", err)

	fmt.Printf("== %d passed, %d failed ==\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
