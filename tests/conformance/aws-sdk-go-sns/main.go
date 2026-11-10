// Real aws-sdk-go-v2 Amazon SNS conformance probe against Vyomi.
//
// Unmodified github.com/aws/aws-sdk-go-v2/service/sns with only BaseEndpoint
// overridden. One [PASS]/[FAIL] line per check; exit 1 on failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/sns"
	"github.com/aws/aws-sdk-go-v2/service/sns/types"
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

type delivery struct {
	Kind     string `json:"kind"`
	Protocol string `json:"protocol"`
	Endpoint string `json:"endpoint"`
	Message  string `json:"message"`
	Token    string `json:"token"`
}

// deliveries reads the appliance's SNS message log (where confirmation tokens and
// non-SQS deliveries are recorded — there is no real mailbox or phone to read).
func deliveries(endpoint string) []delivery {
	resp, err := http.Get(endpoint + "/api/aws/sns/deliveries")
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var out struct {
		Items []delivery `json:"items"`
	}
	_ = json.Unmarshal(b, &out)
	return out.Items
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
	c := sns.NewFromConfig(cfg, func(o *sns.Options) { o.BaseEndpoint = aws.String(endpoint) })
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)
	name := "go-topic-" + sfx

	// topics
	ct, err := c.CreateTopic(ctx, &sns.CreateTopicInput{Name: aws.String(name),
		Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("dev")}}})
	if !step("CreateTopic", err) {
		os.Exit(1)
	}
	arn := aws.ToString(ct.TopicArn)
	chk("topic ARN ends with the name", strings.HasSuffix(arn, ":"+name), arn)
	ct2, err := c.CreateTopic(ctx, &sns.CreateTopicInput{Name: aws.String(name)})
	chk("CreateTopic is idempotent", err == nil && aws.ToString(ct2.TopicArn) == arn, "")
	lt, err := c.ListTopics(ctx, &sns.ListTopicsInput{})
	found := false
	if err == nil {
		for _, t := range lt.Topics {
			found = found || aws.ToString(t.TopicArn) == arn
		}
	}
	chk("ListTopics includes the topic", found, fmt.Sprint(err))
	ga, err := c.GetTopicAttributes(ctx, &sns.GetTopicAttributesInput{TopicArn: aws.String(arn)})
	chk("GetTopicAttributes", err == nil && ga.Attributes["TopicArn"] == arn && ga.Attributes["Owner"] != "" && ga.Attributes["Policy"] != "", fmt.Sprint(err))
	step("SetTopicAttributes DisplayName", func() error {
		_, e := c.SetTopicAttributes(ctx, &sns.SetTopicAttributesInput{TopicArn: aws.String(arn),
			AttributeName: aws.String("DisplayName"), AttributeValue: aws.String("Go topic")})
		return e
	}())
	ga, err = c.GetTopicAttributes(ctx, &sns.GetTopicAttributesInput{TopicArn: aws.String(arn)})
	chk("DisplayName stored", err == nil && ga.Attributes["DisplayName"] == "Go topic", fmt.Sprint(err))
	tg, err := c.ListTagsForResource(ctx, &sns.ListTagsForResourceInput{ResourceArn: aws.String(arn)})
	chk("tags from CreateTopic", err == nil && len(tg.Tags) == 1 && aws.ToString(tg.Tags[0].Key) == "env", fmt.Sprint(err))
	_, err = c.TagResource(ctx, &sns.TagResourceInput{ResourceArn: aws.String(arn), Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("x")}}})
	step("TagResource", err)
	_, err = c.UntagResource(ctx, &sns.UntagResourceInput{ResourceArn: aws.String(arn), TagKeys: []string{"env"}})
	step("UntagResource", err)
	tg, err = c.ListTagsForResource(ctx, &sns.ListTagsForResourceInput{ResourceArn: aws.String(arn)})
	chk("tags after tag/untag", err == nil && len(tg.Tags) == 1 && aws.ToString(tg.Tags[0].Key) == "team", fmt.Sprint(err))
	_, err = c.AddPermission(ctx, &sns.AddPermissionInput{TopicArn: aws.String(arn), Label: aws.String("share"),
		AWSAccountId: []string{"111122223333"}, ActionName: []string{"Publish"}})
	step("AddPermission", err)
	ga, _ = c.GetTopicAttributes(ctx, &sns.GetTopicAttributesInput{TopicArn: aws.String(arn)})
	chk("policy has the new statement", ga != nil && strings.Contains(ga.Attributes["Policy"], "111122223333"), "")
	_, err = c.RemovePermission(ctx, &sns.RemovePermissionInput{TopicArn: aws.String(arn), Label: aws.String("share")})
	step("RemovePermission", err)
	_, err = c.GetTopicAttributes(ctx, &sns.GetTopicAttributesInput{TopicArn: aws.String(arn + "-missing")})
	wantErr("GetTopicAttributes on a missing topic", "NotFound", err)
	_, err = c.CreateTopic(ctx, &sns.CreateTopicInput{Name: aws.String("bad name!")})
	wantErr("CreateTopic rejects a bad name", "InvalidParameter", err)
	dp := `{"Name":"p","Version":"2021-06-01","Statement":[{"DataDirection":"Inbound","Principal":["*"],"DataIdentifier":[]}]}`
	_, err = c.PutDataProtectionPolicy(ctx, &sns.PutDataProtectionPolicyInput{ResourceArn: aws.String(arn), DataProtectionPolicy: aws.String(dp)})
	step("PutDataProtectionPolicy", err)
	gdp, err := c.GetDataProtectionPolicy(ctx, &sns.GetDataProtectionPolicyInput{ResourceArn: aws.String(arn)})
	chk("GetDataProtectionPolicy round-trips", err == nil && strings.Contains(aws.ToString(gdp.DataProtectionPolicy), `"Name":"p"`), fmt.Sprint(err))

	// FIFO
	fifo := "go-fifo-" + sfx + ".fifo"
	cf, err := c.CreateTopic(ctx, &sns.CreateTopicInput{Name: aws.String(fifo),
		Attributes: map[string]string{"FifoTopic": "true", "ContentBasedDeduplication": "true"}})
	if step("CreateTopic (FIFO)", err) {
		farn := aws.ToString(cf.TopicArn)
		_, err = c.Publish(ctx, &sns.PublishInput{TopicArn: aws.String(farn), Message: aws.String("m")})
		wantErr("FIFO publish needs MessageGroupId", "InvalidParameter", err)
		p1, e1 := c.Publish(ctx, &sns.PublishInput{TopicArn: aws.String(farn), Message: aws.String("same"), MessageGroupId: aws.String("g")})
		p2, e2 := c.Publish(ctx, &sns.PublishInput{TopicArn: aws.String(farn), Message: aws.String("same"), MessageGroupId: aws.String("g")})
		chk("FIFO content-based dedup returns the same MessageId + SequenceNumber",
			e1 == nil && e2 == nil && aws.ToString(p1.MessageId) == aws.ToString(p2.MessageId) && aws.ToString(p1.SequenceNumber) != "",
			fmt.Sprint(e1, e2))
		_, err = c.DeleteTopic(ctx, &sns.DeleteTopicInput{TopicArn: aws.String(farn)})
		step("DeleteTopic (FIFO)", err)
	}

	// subscriptions: SQS endpoints are confirmed immediately and Publish fans out
	qname := "go-sns-q-" + sfx
	sub, err := c.Subscribe(ctx, &sns.SubscribeInput{TopicArn: aws.String(arn), Protocol: aws.String("sqs"),
		Endpoint: aws.String("arn:aws:sqs:us-east-1:123456789012:" + qname), ReturnSubscriptionArn: true})
	if step("Subscribe (sqs)", err) {
		sarn := aws.ToString(sub.SubscriptionArn)
		chk("sqs subscription is confirmed", strings.HasPrefix(sarn, arn+":"), sarn)
		_, err = c.SetSubscriptionAttributes(ctx, &sns.SetSubscriptionAttributesInput{SubscriptionArn: aws.String(sarn),
			AttributeName: aws.String("RawMessageDelivery"), AttributeValue: aws.String("true")})
		step("SetSubscriptionAttributes RawMessageDelivery", err)
		_, err = c.SetSubscriptionAttributes(ctx, &sns.SetSubscriptionAttributesInput{SubscriptionArn: aws.String(sarn),
			AttributeName: aws.String("FilterPolicy"), AttributeValue: aws.String(`{"color":["red"]}`)})
		step("SetSubscriptionAttributes FilterPolicy", err)
		gs, err := c.GetSubscriptionAttributes(ctx, &sns.GetSubscriptionAttributesInput{SubscriptionArn: aws.String(sarn)})
		chk("GetSubscriptionAttributes", err == nil && gs.Attributes["Protocol"] == "sqs" && gs.Attributes["RawMessageDelivery"] == "true" && gs.Attributes["FilterPolicy"] != "", fmt.Sprint(err))
		_, err = c.SetSubscriptionAttributes(ctx, &sns.SetSubscriptionAttributesInput{SubscriptionArn: aws.String(sarn),
			AttributeName: aws.String("Nope"), AttributeValue: aws.String("1")})
		wantErr("SetSubscriptionAttributes rejects an unknown attribute", "InvalidParameter", err)
		ls, err := c.ListSubscriptionsByTopic(ctx, &sns.ListSubscriptionsByTopicInput{TopicArn: aws.String(arn)})
		chk("ListSubscriptionsByTopic", err == nil && len(ls.Subscriptions) == 1 && aws.ToString(ls.Subscriptions[0].Protocol) == "sqs", fmt.Sprint(err))
		_, err = c.Unsubscribe(ctx, &sns.UnsubscribeInput{SubscriptionArn: aws.String(sarn)})
		step("Unsubscribe", err)
		_, err = c.Unsubscribe(ctx, &sns.UnsubscribeInput{SubscriptionArn: aws.String(sarn)})
		wantErr("Unsubscribe twice", "NotFound", err)
	}
	_, err = c.Subscribe(ctx, &sns.SubscribeInput{TopicArn: aws.String(arn), Protocol: aws.String("carrier-pigeon"), Endpoint: aws.String("x")})
	wantErr("Subscribe rejects an unknown protocol", "InvalidParameter", err)

	// email: pending until the token from the message log is confirmed
	email := "go-" + sfx + "@example.com"
	es, err := c.Subscribe(ctx, &sns.SubscribeInput{TopicArn: aws.String(arn), Protocol: aws.String("email"), Endpoint: aws.String(email)})
	chk("Subscribe (email) is pending confirmation", err == nil && aws.ToString(es.SubscriptionArn) == "pending confirmation", fmt.Sprint(err))
	token := ""
	for _, d := range deliveries(endpoint) {
		if d.Kind == "SubscriptionConfirmation" && d.Endpoint == email {
			token = d.Token
		}
	}
	chk("confirmation token is in the message log", token != "", "")
	_, err = c.ConfirmSubscription(ctx, &sns.ConfirmSubscriptionInput{TopicArn: aws.String(arn), Token: aws.String("deadbeef")})
	wantErr("ConfirmSubscription with a wrong token", "InvalidParameter", err)
	cs, err := c.ConfirmSubscription(ctx, &sns.ConfirmSubscriptionInput{TopicArn: aws.String(arn), Token: aws.String(token)})
	chk("ConfirmSubscription", err == nil && strings.HasPrefix(aws.ToString(cs.SubscriptionArn), arn+":"), fmt.Sprint(err))
	all, err := c.ListSubscriptions(ctx, &sns.ListSubscriptionsInput{})
	has := false
	if err == nil {
		for _, s := range all.Subscriptions {
			has = has || aws.ToString(s.Endpoint) == email
		}
	}
	chk("ListSubscriptions includes the email subscription", has, fmt.Sprint(err))

	// publish
	pub, err := c.Publish(ctx, &sns.PublishInput{TopicArn: aws.String(arn), Message: aws.String("go-hello"), Subject: aws.String("greeting"),
		MessageAttributes: map[string]types.MessageAttributeValue{"k": {DataType: aws.String("String"), StringValue: aws.String("v")}}})
	chk("Publish returns a MessageId", err == nil && aws.ToString(pub.MessageId) != "", fmt.Sprint(err))
	delivered := false
	for _, d := range deliveries(endpoint) {
		delivered = delivered || (d.Kind == "Notification" && d.Protocol == "email" && d.Message == "go-hello")
	}
	chk("Publish was delivered to the email subscription (message log)", delivered, "")
	_, err = c.Publish(ctx, &sns.PublishInput{TopicArn: aws.String(arn), Message: aws.String("")})
	wantErr("Publish rejects an empty message", "InvalidParameter", err)
	_, err = c.Publish(ctx, &sns.PublishInput{TopicArn: aws.String(arn + "-missing"), Message: aws.String("x")})
	wantErr("Publish to a missing topic", "NotFound", err)
	pb, err := c.PublishBatch(ctx, &sns.PublishBatchInput{TopicArn: aws.String(arn), PublishBatchRequestEntries: []types.PublishBatchRequestEntry{
		{Id: aws.String("a"), Message: aws.String("m1")}, {Id: aws.String("b"), Message: aws.String("")}}})
	chk("PublishBatch reports per-entry results", err == nil && len(pb.Successful) == 1 && len(pb.Failed) == 1 && aws.ToString(pb.Failed[0].Id) == "b", fmt.Sprint(err))
	_, err = c.PublishBatch(ctx, &sns.PublishBatchInput{TopicArn: aws.String(arn), PublishBatchRequestEntries: []types.PublishBatchRequestEntry{
		{Id: aws.String("a"), Message: aws.String("m1")}, {Id: aws.String("a"), Message: aws.String("m2")}}})
	wantErr("PublishBatch rejects duplicate ids", "BatchEntryIdsNotDistinct", err)

	// mobile push
	pa, err := c.CreatePlatformApplication(ctx, &sns.CreatePlatformApplicationInput{Name: aws.String("go-app-" + sfx), Platform: aws.String("GCM"),
		Attributes: map[string]string{"PlatformCredential": "go-key"}})
	if step("CreatePlatformApplication", err) {
		paarn := aws.ToString(pa.PlatformApplicationArn)
		pat, err := c.GetPlatformApplicationAttributes(ctx, &sns.GetPlatformApplicationAttributesInput{PlatformApplicationArn: aws.String(paarn)})
		_, leaked := pat.Attributes["PlatformCredential"]
		chk("GetPlatformApplicationAttributes (credential not echoed)", err == nil && !leaked && pat.Attributes["Enabled"] == "true", fmt.Sprint(err))
		lpa, err := c.ListPlatformApplications(ctx, &sns.ListPlatformApplicationsInput{})
		okApp := false
		if err == nil {
			for _, a := range lpa.PlatformApplications {
				okApp = okApp || aws.ToString(a.PlatformApplicationArn) == paarn
			}
		}
		chk("ListPlatformApplications", okApp, fmt.Sprint(err))
		pe, err := c.CreatePlatformEndpoint(ctx, &sns.CreatePlatformEndpointInput{PlatformApplicationArn: aws.String(paarn), Token: aws.String("tok-" + sfx)})
		if step("CreatePlatformEndpoint", err) {
			earn := aws.ToString(pe.EndpointArn)
			pe2, err := c.CreatePlatformEndpoint(ctx, &sns.CreatePlatformEndpointInput{PlatformApplicationArn: aws.String(paarn), Token: aws.String("tok-" + sfx)})
			chk("CreatePlatformEndpoint is idempotent per token", err == nil && aws.ToString(pe2.EndpointArn) == earn, fmt.Sprint(err))
			le, err := c.ListEndpointsByPlatformApplication(ctx, &sns.ListEndpointsByPlatformApplicationInput{PlatformApplicationArn: aws.String(paarn)})
			chk("ListEndpointsByPlatformApplication", err == nil && len(le.Endpoints) == 1, fmt.Sprint(err))
			_, err = c.Publish(ctx, &sns.PublishInput{TargetArn: aws.String(earn), Message: aws.String(`{"GCM":"{\"data\":{\"m\":1}}"}`), MessageStructure: aws.String("json")})
			step("Publish to the endpoint", err)
			_, err = c.SetEndpointAttributes(ctx, &sns.SetEndpointAttributesInput{EndpointArn: aws.String(earn), Attributes: map[string]string{"Enabled": "false"}})
			step("SetEndpointAttributes Enabled=false", err)
			ea, err := c.GetEndpointAttributes(ctx, &sns.GetEndpointAttributesInput{EndpointArn: aws.String(earn)})
			chk("GetEndpointAttributes", err == nil && ea.Attributes["Enabled"] == "false" && ea.Attributes["Token"] == "tok-"+sfx, fmt.Sprint(err))
			_, err = c.Publish(ctx, &sns.PublishInput{TargetArn: aws.String(earn), Message: aws.String("x")})
			wantErr("Publish to a disabled endpoint", "EndpointDisabled", err)
			_, err = c.DeleteEndpoint(ctx, &sns.DeleteEndpointInput{EndpointArn: aws.String(earn)})
			step("DeleteEndpoint", err)
		}
		_, err = c.SetPlatformApplicationAttributes(ctx, &sns.SetPlatformApplicationAttributesInput{PlatformApplicationArn: aws.String(paarn), Attributes: map[string]string{"Enabled": "false"}})
		step("SetPlatformApplicationAttributes", err)
		_, err = c.DeletePlatformApplication(ctx, &sns.DeletePlatformApplicationInput{PlatformApplicationArn: aws.String(paarn)})
		step("DeletePlatformApplication", err)
	}

	// SMS
	_, err = c.SetSMSAttributes(ctx, &sns.SetSMSAttributesInput{Attributes: map[string]string{"DefaultSMSType": "Transactional"}})
	step("SetSMSAttributes", err)
	sa, err := c.GetSMSAttributes(ctx, &sns.GetSMSAttributesInput{})
	chk("GetSMSAttributes", err == nil && sa.Attributes["DefaultSMSType"] == "Transactional", fmt.Sprint(err))
	st, err := c.GetSMSSandboxAccountStatus(ctx, &sns.GetSMSSandboxAccountStatusInput{})
	chk("GetSMSSandboxAccountStatus", err == nil && st.IsInSandbox, fmt.Sprint(err))
	phone := "+1555555" + fmt.Sprintf("%04d", time.Now().UnixNano()%10000)
	_, err = c.CreateSMSSandboxPhoneNumber(ctx, &sns.CreateSMSSandboxPhoneNumberInput{PhoneNumber: aws.String(phone)})
	step("CreateSMSSandboxPhoneNumber", err)
	_, err = c.VerifySMSSandboxPhoneNumber(ctx, &sns.VerifySMSSandboxPhoneNumberInput{PhoneNumber: aws.String(phone), OneTimePassword: aws.String("000000")})
	wantErr("VerifySMSSandboxPhoneNumber with a wrong OTP", "VerificationException", err)
	otp := ""
	for _, d := range deliveries(endpoint) {
		if d.Kind == "SMSSandboxVerification" && d.Endpoint == phone {
			otp = d.Token
		}
	}
	_, err = c.VerifySMSSandboxPhoneNumber(ctx, &sns.VerifySMSSandboxPhoneNumberInput{PhoneNumber: aws.String(phone), OneTimePassword: aws.String(otp)})
	step("VerifySMSSandboxPhoneNumber", err)
	sl, err := c.ListSMSSandboxPhoneNumbers(ctx, &sns.ListSMSSandboxPhoneNumbersInput{})
	verified := false
	if err == nil {
		for _, n := range sl.PhoneNumbers {
			verified = verified || (aws.ToString(n.PhoneNumber) == phone && n.Status == types.SMSSandboxPhoneNumberVerificationStatusVerified)
		}
	}
	chk("ListSMSSandboxPhoneNumbers shows it verified", verified, fmt.Sprint(err))
	_, err = c.Publish(ctx, &sns.PublishInput{PhoneNumber: aws.String(phone), Message: aws.String("hi")})
	step("Publish an SMS to the verified number", err)
	oo, err := c.CheckIfPhoneNumberIsOptedOut(ctx, &sns.CheckIfPhoneNumberIsOptedOutInput{PhoneNumber: aws.String(phone)})
	chk("CheckIfPhoneNumberIsOptedOut", err == nil && !oo.IsOptedOut, fmt.Sprint(err))
	_, err = c.ListPhoneNumbersOptedOut(ctx, &sns.ListPhoneNumbersOptedOutInput{})
	step("ListPhoneNumbersOptedOut", err)
	_, err = c.OptInPhoneNumber(ctx, &sns.OptInPhoneNumberInput{PhoneNumber: aws.String(phone)})
	step("OptInPhoneNumber", err)
	_, err = c.ListOriginationNumbers(ctx, &sns.ListOriginationNumbersInput{})
	step("ListOriginationNumbers", err)
	_, err = c.DeleteSMSSandboxPhoneNumber(ctx, &sns.DeleteSMSSandboxPhoneNumberInput{PhoneNumber: aws.String(phone)})
	step("DeleteSMSSandboxPhoneNumber", err)

	// delete
	_, err = c.DeleteTopic(ctx, &sns.DeleteTopicInput{TopicArn: aws.String(arn)})
	step("DeleteTopic", err)
	_, err = c.GetTopicAttributes(ctx, &sns.GetTopicAttributesInput{TopicArn: aws.String(arn)})
	wantErr("deleted topic is gone", "NotFound", err)

	fmt.Printf("aws-sdk-go sns: %d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
