package cloudlearn.orders;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.eventbridge.EventBridgeClient;
import software.amazon.awssdk.services.iam.IamClient;
import software.amazon.awssdk.services.kms.KmsClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sts.StsClient;

import java.net.URI;

/**
 * One bean per AWS SDK v2 client. All clients are pointed at the CloudLearn
 * simulator via endpointOverride. SigV4 with fake creds (the simulator ignores
 * them); S3 forced to path-style + chunked-encoding disabled (works around the
 * aws-chunked P1 gap documented in mvp-launch-ready-p0-batch.md).
 */
@Configuration
public class AwsConfig {

    @Value("${cloudlearn.endpoint}")
    private String endpoint;

    @Value("${cloudlearn.region}")
    private String region;

    @Value("${cloudlearn.access-key}")
    private String accessKey;

    @Value("${cloudlearn.secret-key}")
    private String secretKey;

    private StaticCredentialsProvider creds() {
        return StaticCredentialsProvider.create(AwsBasicCredentials.create(accessKey, secretKey));
    }

    private URI uri() {
        return URI.create(endpoint);
    }

    @Bean
    public S3Client s3Client() {
        return S3Client.builder()
                .endpointOverride(uri())
                .region(Region.of(region))
                .credentialsProvider(creds())
                .serviceConfiguration(S3Configuration.builder()
                        .pathStyleAccessEnabled(true)
                        .chunkedEncodingEnabled(false)
                        .build())
                .build();
    }

    @Bean
    public SqsClient sqsClient() {
        return SqsClient.builder()
                .endpointOverride(uri()).region(Region.of(region))
                .credentialsProvider(creds()).build();
    }

    @Bean
    public SecretsManagerClient secretsManagerClient() {
        return SecretsManagerClient.builder()
                .endpointOverride(uri()).region(Region.of(region))
                .credentialsProvider(creds()).build();
    }

    @Bean
    public KmsClient kmsClient() {
        return KmsClient.builder()
                .endpointOverride(uri()).region(Region.of(region))
                .credentialsProvider(creds()).build();
    }

    @Bean
    public EventBridgeClient eventBridgeClient() {
        return EventBridgeClient.builder()
                .endpointOverride(uri()).region(Region.of(region))
                .credentialsProvider(creds()).build();
    }

    @Bean
    public IamClient iamClient() {
        return IamClient.builder()
                .endpointOverride(uri()).region(Region.AWS_GLOBAL)
                .credentialsProvider(creds()).build();
    }

    @Bean
    public StsClient stsClient() {
        return StsClient.builder()
                .endpointOverride(uri()).region(Region.of(region))
                .credentialsProvider(creds()).build();
    }
}
