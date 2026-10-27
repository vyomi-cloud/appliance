// Real aws-sdk-java-v2 Amazon SES v2 conformance probe against Vyomi.
//
// Unmodified software.amazon.awssdk.services.sesv2 with only the endpoint
// overridden. One [PASS]/[FAIL] line per check; exit code 1 on any failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=SesV2Conformance

import java.net.URI;
import java.util.function.Supplier;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.sesv2.SesV2Client;
import software.amazon.awssdk.services.sesv2.model.*;

public class SesV2Conformance {

    static int pass = 0;
    static int fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) {
            pass++;
            System.out.println("[PASS] " + name);
        } else {
            fail++;
            System.out.println("[FAIL] " + name + (detail == null || detail.isEmpty() ? "" : " :: " + detail));
        }
    }

    static void chk(String name, boolean ok) {
        chk(name, ok, "");
    }

    static <T> T run(String name, Supplier<T> fn) {
        try {
            T v = fn.get();
            chk(name, true, "");
            return v;
        } catch (Exception e) {
            chk(name, false, e.toString());
            return null;
        }
    }

    /** Expect the call to fail with the given error code. */
    static void expectError(String name, String code, Runnable fn) {
        try {
            fn.run();
            chk(name, false, "expected " + code + " but the call succeeded");
        } catch (SesV2Exception e) {
            String got = e.awsErrorDetails() == null ? "" : e.awsErrorDetails().errorCode();
            chk(name, code.equals(got), "expected " + code + " got " + got);
        } catch (Exception e) {
            chk(name, false, e.toString());
        }
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        SesV2Client ses = SesV2Client.builder()
                .endpointOverride(URI.create(endpoint))
                .region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
                .build();
        String sfx = Long.toString(System.currentTimeMillis() % 1000000);
        String email = "java-" + sfx + "@example.com";
        String domain = "java-" + sfx + ".example.org";
        String cs = "java-cs-" + sfx, tpl = "java-tpl-" + sfx, list = "java-list-" + sfx;

        // identities
        CreateEmailIdentityResponse ci = run("CreateEmailIdentity (address)", () ->
                ses.createEmailIdentity(CreateEmailIdentityRequest.builder().emailIdentity(email).build()));
        if (ci == null) System.exit(1);
        chk("address identity is verified", ci.identityType() == IdentityType.EMAIL_ADDRESS && ci.verifiedForSendingStatus(), String.valueOf(ci));
        CreateEmailIdentityResponse cd = run("CreateEmailIdentity (domain)", () ->
                ses.createEmailIdentity(CreateEmailIdentityRequest.builder().emailIdentity(domain).build()));
        chk("domain identity has 3 DKIM tokens", cd != null && cd.dkimAttributes().tokens().size() == 3, String.valueOf(cd));
        expectError("duplicate identity -> AlreadyExistsException", "AlreadyExistsException", () ->
                ses.createEmailIdentity(CreateEmailIdentityRequest.builder().emailIdentity(email).build()));
        GetEmailIdentityResponse gi = run("GetEmailIdentity", () ->
                ses.getEmailIdentity(GetEmailIdentityRequest.builder().emailIdentity(email).build()));
        chk("identity details", gi != null && gi.verificationStatus() == VerificationStatus.SUCCESS, String.valueOf(gi));
        expectError("unknown identity -> NotFoundException", "NotFoundException", () ->
                ses.getEmailIdentity(GetEmailIdentityRequest.builder().emailIdentity("none-" + sfx + "@example.com").build()));
        ListEmailIdentitiesResponse li = run("ListEmailIdentities", () -> ses.listEmailIdentities(ListEmailIdentitiesRequest.builder().build()));
        chk("list contains both identities", li != null && li.emailIdentities().stream().anyMatch(i -> i.identityName().equals(domain))
                && li.emailIdentities().stream().anyMatch(i -> i.identityName().equals(email)));
        run("PutEmailIdentityMailFromAttributes", () -> ses.putEmailIdentityMailFromAttributes(PutEmailIdentityMailFromAttributesRequest.builder()
                .emailIdentity(domain).mailFromDomain("mail." + domain).behaviorOnMxFailure(BehaviorOnMxFailure.REJECT_MESSAGE).build()));
        GetEmailIdentityResponse gd = ses.getEmailIdentity(GetEmailIdentityRequest.builder().emailIdentity(domain).build());
        chk("mail-from persisted", gd.mailFromAttributes() != null && gd.mailFromAttributes().mailFromDomain().equals("mail." + domain));

        // configuration set + event destination
        run("CreateConfigurationSet", () -> ses.createConfigurationSet(CreateConfigurationSetRequest.builder()
                .configurationSetName(cs).sendingOptions(SendingOptions.builder().sendingEnabled(true).build()).build()));
        GetConfigurationSetResponse gcs = run("GetConfigurationSet", () -> ses.getConfigurationSet(GetConfigurationSetRequest.builder().configurationSetName(cs).build()));
        chk("config set name", gcs != null && gcs.configurationSetName().equals(cs));
        run("PutConfigurationSetDeliveryOptions", () -> ses.putConfigurationSetDeliveryOptions(PutConfigurationSetDeliveryOptionsRequest.builder()
                .configurationSetName(cs).tlsPolicy(TlsPolicy.REQUIRE).build()));
        run("CreateConfigurationSetEventDestination", () -> ses.createConfigurationSetEventDestination(CreateConfigurationSetEventDestinationRequest.builder()
                .configurationSetName(cs).eventDestinationName("sns1").eventDestination(EventDestinationDefinition.builder().enabled(true)
                        .matchingEventTypes(EventType.SEND, EventType.BOUNCE)
                        .snsDestination(SnsDestination.builder().topicArn("arn:aws:sns:us-east-1:123456789012:t").build()).build()).build()));
        GetConfigurationSetEventDestinationsResponse ed = run("GetConfigurationSetEventDestinations", () ->
                ses.getConfigurationSetEventDestinations(GetConfigurationSetEventDestinationsRequest.builder().configurationSetName(cs).build()));
        chk("event destination returned", ed != null && ed.eventDestinations().size() == 1 && ed.eventDestinations().get(0).matchingEventTypes().size() == 2);
        ListConfigurationSetsResponse lcs = run("ListConfigurationSets", () -> ses.listConfigurationSets(ListConfigurationSetsRequest.builder().build()));
        chk("config set listed", lcs != null && lcs.configurationSets().contains(cs));

        // templates
        run("CreateEmailTemplate", () -> ses.createEmailTemplate(CreateEmailTemplateRequest.builder().templateName(tpl)
                .templateContent(EmailTemplateContent.builder().subject("Hi {{name}}").text("Hello {{name}}").html("<b>{{name}}</b>").build()).build()));
        TestRenderEmailTemplateResponse tr = run("TestRenderEmailTemplate", () -> ses.testRenderEmailTemplate(TestRenderEmailTemplateRequest.builder()
                .templateName(tpl).templateData("{\"name\":\"Ada\"}").build()));
        chk("template rendered", tr != null && tr.renderedTemplate().contains("Subject: Hi Ada"));
        run("UpdateEmailTemplate", () -> ses.updateEmailTemplate(UpdateEmailTemplateRequest.builder().templateName(tpl)
                .templateContent(EmailTemplateContent.builder().subject("Welcome {{name}}").text("t").build()).build()));
        GetEmailTemplateResponse gt = ses.getEmailTemplate(GetEmailTemplateRequest.builder().templateName(tpl).build());
        chk("template updated", gt.templateContent().subject().equals("Welcome {{name}}"));
        ListEmailTemplatesResponse lt = run("ListEmailTemplates", () -> ses.listEmailTemplates(ListEmailTemplatesRequest.builder().build()));
        chk("template listed", lt != null && lt.templatesMetadata().stream().anyMatch(t -> t.templateName().equals(tpl)));

        // sending
        SendEmailResponse se = run("SendEmail (Simple)", () -> ses.sendEmail(SendEmailRequest.builder().fromEmailAddress(email)
                .destination(Destination.builder().toAddresses("to@example.net").build()).configurationSetName(cs)
                .content(EmailContent.builder().simple(Message.builder().subject(Content.builder().data("hello").build())
                        .body(Body.builder().text(Content.builder().data("world").build()).build()).build()).build()).build()));
        chk("MessageId returned", se != null && se.messageId() != null && se.messageId().length() > 10);
        run("SendEmail (from a verified domain)", () -> ses.sendEmail(SendEmailRequest.builder().fromEmailAddress("anyone@" + domain)
                .destination(Destination.builder().toAddresses("to@example.net").build())
                .content(EmailContent.builder().template(Template.builder().templateName(tpl).templateData("{}").build()).build()).build()));
        expectError("unverified sender -> MessageRejected", "MessageRejected", () -> ses.sendEmail(SendEmailRequest.builder()
                .fromEmailAddress("x@unverified-" + sfx + ".com").destination(Destination.builder().toAddresses("to@example.net").build())
                .content(EmailContent.builder().simple(Message.builder().subject(Content.builder().data("a").build())
                        .body(Body.builder().text(Content.builder().data("b").build()).build()).build()).build()).build()));
        SendBulkEmailResponse sb = run("SendBulkEmail", () -> ses.sendBulkEmail(SendBulkEmailRequest.builder().fromEmailAddress(email)
                .defaultContent(BulkEmailContent.builder().template(Template.builder().templateName(tpl).templateData("{}").build()).build())
                .bulkEmailEntries(BulkEmailEntry.builder().destination(Destination.builder().toAddresses("a@example.net").build()).build()).build()));
        chk("bulk entry succeeded", sb != null && sb.bulkEmailEntryResults().get(0).status() == BulkEmailStatus.SUCCESS);

        // contact lists
        run("CreateContactList", () -> ses.createContactList(CreateContactListRequest.builder().contactListName(list).description("d")
                .topics(Topic.builder().topicName("news").displayName("News").description("d").defaultSubscriptionStatus(SubscriptionStatus.OPT_IN).build()).build()));
        run("CreateContact", () -> ses.createContact(CreateContactRequest.builder().contactListName(list).emailAddress("sub@example.net").build()));
        GetContactResponse gc = run("GetContact", () -> ses.getContact(GetContactRequest.builder().contactListName(list).emailAddress("sub@example.net").build()));
        chk("topic default inherited", gc != null && gc.topicDefaultPreferences().get(0).subscriptionStatus() == SubscriptionStatus.OPT_IN);
        ListContactsResponse lc = run("ListContacts", () -> ses.listContacts(ListContactsRequest.builder().contactListName(list).build()));
        chk("contact listed", lc != null && lc.contacts().size() == 1);

        // suppression, tags, account
        run("PutSuppressedDestination", () -> ses.putSuppressedDestination(PutSuppressedDestinationRequest.builder()
                .emailAddress("bounce-" + sfx + "@example.net").reason(SuppressionListReason.BOUNCE).build()));
        GetSuppressedDestinationResponse gs = run("GetSuppressedDestination", () -> ses.getSuppressedDestination(
                GetSuppressedDestinationRequest.builder().emailAddress("bounce-" + sfx + "@example.net").build()));
        chk("suppression reason", gs != null && gs.suppressedDestination().reason() == SuppressionListReason.BOUNCE);
        run("DeleteSuppressedDestination", () -> ses.deleteSuppressedDestination(DeleteSuppressedDestinationRequest.builder().emailAddress("bounce-" + sfx + "@example.net").build()));
        String arn = "arn:aws:ses:us-east-1:123456789012:identity/" + email;
        run("TagResource", () -> ses.tagResource(TagResourceRequest.builder().resourceArn(arn)
                .tags(Tag.builder().key("team").value("mail").build(), Tag.builder().key("env").value("dev").build()).build()));
        ListTagsForResourceResponse lt2 = run("ListTagsForResource", () -> ses.listTagsForResource(ListTagsForResourceRequest.builder().resourceArn(arn).build()));
        chk("tags listed", lt2 != null && lt2.tags().size() == 2);
        run("UntagResource", () -> ses.untagResource(UntagResourceRequest.builder().resourceArn(arn).tagKeys("team", "env").build()));
        chk("tags removed", ses.listTagsForResource(ListTagsForResourceRequest.builder().resourceArn(arn).build()).tags().isEmpty());
        GetAccountResponse ga = run("GetAccount", () -> ses.getAccount(GetAccountRequest.builder().build()));
        chk("account quota", ga != null && ga.sendQuota().max24HourSend() > 0 && ga.sendingEnabled());

        // cleanup
        run("DeleteContact", () -> ses.deleteContact(DeleteContactRequest.builder().contactListName(list).emailAddress("sub@example.net").build()));
        run("DeleteContactList", () -> ses.deleteContactList(DeleteContactListRequest.builder().contactListName(list).build()));
        run("DeleteEmailTemplate", () -> ses.deleteEmailTemplate(DeleteEmailTemplateRequest.builder().templateName(tpl).build()));
        run("DeleteConfigurationSet", () -> ses.deleteConfigurationSet(DeleteConfigurationSetRequest.builder().configurationSetName(cs).build()));
        run("DeleteEmailIdentity (address)", () -> ses.deleteEmailIdentity(DeleteEmailIdentityRequest.builder().emailIdentity(email).build()));
        run("DeleteEmailIdentity (domain)", () -> ses.deleteEmailIdentity(DeleteEmailIdentityRequest.builder().emailIdentity(domain).build()));
        expectError("deleted identity is gone", "NotFoundException", () ->
                ses.getEmailIdentity(GetEmailIdentityRequest.builder().emailIdentity(email).build()));

        System.out.println("== " + pass + " passed, " + fail + " failed ==");
        System.exit(fail == 0 ? 0 : 1);
    }
}
