import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.cognitoidentityprovider.CognitoIdentityProviderClient;
import software.amazon.awssdk.services.cognitoidentityprovider.model.*;

/**
 * Amazon Cognito user pools — real AWS SDK v2 against Vyomi (endpoint override only).
 * Run: ENDPOINT=http://localhost:9000 mvn -q -B compile exec:java -Dexec.mainClass=AwsCognitoIdpConformance
 * Prints one [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class AwsCognitoIdpConformance {
    static int pass = 0, fail = 0;

    static void check(String name, boolean ok, String detail) {
        if (ok) { pass++; System.out.println("[PASS] " + name); }
        else { fail++; System.out.println("[FAIL] " + name + (detail.isEmpty() ? "" : " :: " + detail)); }
    }

    static void run(String name, Runnable r) {
        try { r.run(); } catch (Throwable t) { check(name, false, t.toString()); }
    }

    static <T extends Throwable> void expect(String name, Class<T> type, Runnable r) {
        try { r.run(); check(name, false, "no exception"); }
        catch (Throwable t) { check(name, type.isInstance(t), t.toString()); }
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://localhost:9000");
        CognitoIdentityProviderClient c = CognitoIdentityProviderClient.builder()
            .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test"))).build();
        String suffix = Long.toString(System.nanoTime() % 1000000);
        String[] ids = new String[3];   // pool, client, user pool 2

        run("CreateUserPool", () -> {
            UserPoolType p = c.createUserPool(b -> b.poolName("java-pool-" + suffix)
                .autoVerifiedAttributes(VerifiedAttributeType.EMAIL)
                .policies(UserPoolPolicyType.builder().passwordPolicy(PasswordPolicyType.builder().minimumLength(8).build()).build())).userPool();
            ids[0] = p.id();
            check("CreateUserPool returns id/arn", p.id().startsWith("us-east-1_") && p.arn().contains(":userpool/" + p.id()), p.toString());
        });
        run("DescribeUserPool", () -> check("DescribeUserPool name", c.describeUserPool(b -> b.userPoolId(ids[0])).userPool().name().equals("java-pool-" + suffix), ""));
        run("ListUserPools", () -> check("ListUserPools contains pool",
            c.listUserPools(b -> b.maxResults(60)).userPools().stream().anyMatch(x -> x.id().equals(ids[0])), ""));
        run("UpdateUserPool", () -> { c.updateUserPool(b -> b.userPoolId(ids[0]).userPoolTags(Map.of("env", "test"))); check("UpdateUserPool tags",
            c.listTagsForResource(b -> b.resourceArn(c.describeUserPool(d -> d.userPoolId(ids[0])).userPool().arn())).tags().containsKey("env"), ""); });

        run("CreateUserPoolClient", () -> {
            UserPoolClientType cl = c.createUserPoolClient(b -> b.userPoolId(ids[0]).clientName("java-client")
                .explicitAuthFlows(ExplicitAuthFlowsType.ALLOW_USER_PASSWORD_AUTH, ExplicitAuthFlowsType.ALLOW_ADMIN_USER_PASSWORD_AUTH, ExplicitAuthFlowsType.ALLOW_REFRESH_TOKEN_AUTH)).userPoolClient();
            ids[1] = cl.clientId();
            check("CreateUserPoolClient id", cl.clientId().length() == 26, cl.clientId());
        });
        run("ListUserPoolClients", () -> check("ListUserPoolClients", c.listUserPoolClients(b -> b.userPoolId(ids[0]).maxResults(10)).userPoolClients().size() == 1, ""));

        run("SignUp", () -> {
            SignUpResponse r = c.signUp(b -> b.clientId(ids[1]).username("alice").password("Passw0rd!x")
                .userAttributes(AttributeType.builder().name("email").value("alice@example.com").build()));
            check("SignUp unconfirmed", !r.userConfirmed() && r.userSub().length() == 36, "");
        });
        expect("SignUp duplicate -> UsernameExistsException", UsernameExistsException.class,
            () -> c.signUp(b -> b.clientId(ids[1]).username("alice").password("Passw0rd!x")));
        expect("SignUp weak password -> InvalidPasswordException", InvalidPasswordException.class,
            () -> c.signUp(b -> b.clientId(ids[1]).username("weak").password("alllowercase1!")));
        expect("InitiateAuth unconfirmed -> UserNotConfirmedException", UserNotConfirmedException.class,
            () -> c.initiateAuth(b -> b.clientId(ids[1]).authFlow(AuthFlowType.USER_PASSWORD_AUTH).authParameters(Map.of("USERNAME", "alice", "PASSWORD", "Passw0rd!x"))));
        run("ConfirmSignUp", () -> { c.confirmSignUp(b -> b.clientId(ids[1]).username("alice").confirmationCode("123456")); check("ConfirmSignUp", true, ""); });
        expect("InitiateAuth wrong password -> NotAuthorizedException", NotAuthorizedException.class,
            () -> c.initiateAuth(b -> b.clientId(ids[1]).authFlow(AuthFlowType.USER_PASSWORD_AUTH).authParameters(Map.of("USERNAME", "alice", "PASSWORD", "nope"))));

        String[] tokens = new String[3];
        run("InitiateAuth USER_PASSWORD_AUTH", () -> {
            AuthenticationResultType a = c.initiateAuth(b -> b.clientId(ids[1]).authFlow(AuthFlowType.USER_PASSWORD_AUTH)
                .authParameters(Map.of("USERNAME", "alice", "PASSWORD", "Passw0rd!x"))).authenticationResult();
            tokens[0] = a.accessToken(); tokens[1] = a.idToken(); tokens[2] = a.refreshToken();
            check("tokens issued", a.accessToken().split("\\.").length == 3 && a.idToken().split("\\.").length == 3 && a.refreshToken() != null && a.expiresIn() == 3600, "");
        });
        run("GetUser", () -> { GetUserResponse g = c.getUser(b -> b.accessToken(tokens[0]));
            check("GetUser attributes", g.username().equals("alice") && g.userAttributes().stream().anyMatch(a -> a.name().equals("email") && a.value().equals("alice@example.com")), g.toString()); });
        run("UpdateUserAttributes", () -> { c.updateUserAttributes(b -> b.accessToken(tokens[0]).userAttributes(AttributeType.builder().name("given_name").value("Alice").build()));
            check("UpdateUserAttributes", c.getUser(b -> b.accessToken(tokens[0])).userAttributes().stream().anyMatch(a -> a.name().equals("given_name")), ""); });
        run("REFRESH_TOKEN_AUTH", () -> check("refresh issues new access token",
            c.initiateAuth(b -> b.clientId(ids[1]).authFlow(AuthFlowType.REFRESH_TOKEN_AUTH).authParameters(Map.of("REFRESH_TOKEN", tokens[2]))).authenticationResult().accessToken() != null, ""));
        run("ChangePassword", () -> { c.changePassword(b -> b.accessToken(tokens[0]).previousPassword("Passw0rd!x").proposedPassword("N3wPassw0rd!")); check("ChangePassword", true, ""); });
        run("GlobalSignOut", () -> { c.globalSignOut(b -> b.accessToken(tokens[0])); check("GlobalSignOut", true, ""); });
        expect("GetUser after sign-out -> NotAuthorizedException", NotAuthorizedException.class, () -> c.getUser(b -> b.accessToken(tokens[0])));

        run("AdminCreateUser", () -> {
            UserType u = c.adminCreateUser(b -> b.userPoolId(ids[0]).username("bob").temporaryPassword("Temp#Pass1")
                .userAttributes(AttributeType.builder().name("email").value("bob@example.com").build())).user();
            check("AdminCreateUser FORCE_CHANGE_PASSWORD", u.userStatus() == UserStatusType.FORCE_CHANGE_PASSWORD && u.enabled(), u.toString());
        });
        run("NEW_PASSWORD_REQUIRED challenge", () -> {
            AdminInitiateAuthResponse r = c.adminInitiateAuth(b -> b.userPoolId(ids[0]).clientId(ids[1]).authFlow(AuthFlowType.ADMIN_USER_PASSWORD_AUTH)
                .authParameters(Map.of("USERNAME", "bob", "PASSWORD", "Temp#Pass1")));
            check("challenge returned", r.challengeName() == ChallengeNameType.NEW_PASSWORD_REQUIRED, "");
            AdminRespondToAuthChallengeResponse d = c.adminRespondToAuthChallenge(b -> b.userPoolId(ids[0]).clientId(ids[1])
                .challengeName(ChallengeNameType.NEW_PASSWORD_REQUIRED).session(r.session()).challengeResponses(Map.of("USERNAME", "bob", "NEW_PASSWORD", "Perm#anent9")));
            check("challenge completes", d.authenticationResult() != null, "");
        });
        run("AdminGetUser", () -> check("AdminGetUser CONFIRMED", c.adminGetUser(b -> b.userPoolId(ids[0]).username("bob")).userStatus() == UserStatusType.CONFIRMED, ""));
        run("AdminDisableUser/AdminEnableUser", () -> {
            c.adminDisableUser(b -> b.userPoolId(ids[0]).username("bob"));
            boolean off = !c.adminGetUser(b -> b.userPoolId(ids[0]).username("bob")).enabled();
            c.adminEnableUser(b -> b.userPoolId(ids[0]).username("bob"));
            check("disable then enable", off && c.adminGetUser(b -> b.userPoolId(ids[0]).username("bob")).enabled(), "");
        });
        run("ListUsers filter", () -> check("ListUsers Filter email",
            c.listUsers(b -> b.userPoolId(ids[0]).filter("email = \"bob@example.com\"")).users().size() == 1 && c.listUsers(b -> b.userPoolId(ids[0])).users().size() == 2, ""));

        run("Groups", () -> {
            c.createGroup(b -> b.userPoolId(ids[0]).groupName("admins").description("Administrators").precedence(1));
            c.adminAddUserToGroup(b -> b.userPoolId(ids[0]).username("bob").groupName("admins"));
            check("AdminListGroupsForUser", c.adminListGroupsForUser(b -> b.userPoolId(ids[0]).username("bob")).groups().get(0).groupName().equals("admins"), "");
            check("ListUsersInGroup", c.listUsersInGroup(b -> b.userPoolId(ids[0]).groupName("admins")).users().size() == 1, "");
            c.adminRemoveUserFromGroup(b -> b.userPoolId(ids[0]).username("bob").groupName("admins"));
            c.deleteGroup(b -> b.userPoolId(ids[0]).groupName("admins"));
            check("DeleteGroup", c.listGroups(b -> b.userPoolId(ids[0])).groups().isEmpty(), "");
        });
        run("Domain", () -> {
            c.createUserPoolDomain(b -> b.userPoolId(ids[0]).domain("java-auth-" + suffix));
            check("DescribeUserPoolDomain", c.describeUserPoolDomain(b -> b.domain("java-auth-" + suffix)).domainDescription().userPoolId().equals(ids[0]), "");
            c.deleteUserPoolDomain(b -> b.userPoolId(ids[0]).domain("java-auth-" + suffix));
        });
        run("ForgotPassword", () -> {
            c.forgotPassword(b -> b.clientId(ids[1]).username("alice"));
            c.confirmForgotPassword(b -> b.clientId(ids[1]).username("alice").confirmationCode("123456").password("Another1!pw"));
            check("ConfirmForgotPassword then sign in", c.initiateAuth(b -> b.clientId(ids[1]).authFlow(AuthFlowType.USER_PASSWORD_AUTH)
                .authParameters(Map.of("USERNAME", "alice", "PASSWORD", "Another1!pw"))).authenticationResult() != null, "");
        });
        expect("DescribeUserPool unknown -> ResourceNotFoundException", ResourceNotFoundException.class,
            () -> c.describeUserPool(b -> b.userPoolId("us-east-1_doesnotexist")));
        run("AdminDeleteUser", () -> { c.adminDeleteUser(b -> b.userPoolId(ids[0]).username("bob")); check("AdminDeleteUser", c.listUsers(b -> b.userPoolId(ids[0])).users().size() == 1, ""); });
        run("DeleteUserPoolClient", () -> { c.deleteUserPoolClient(b -> b.userPoolId(ids[0]).clientId(ids[1])); check("DeleteUserPoolClient", c.listUserPoolClients(b -> b.userPoolId(ids[0]).maxResults(10)).userPoolClients().isEmpty(), ""); });
        run("DeleteUserPool", () -> { c.deleteUserPool(b -> b.userPoolId(ids[0])); check("DeleteUserPool", c.listUserPools(b -> b.maxResults(60)).userPools().stream().noneMatch(x -> x.id().equals(ids[0])), ""); });

        System.out.println(pass + " passed, " + fail + " failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}
