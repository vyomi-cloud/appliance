package com.example;

import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.sqs.SqsClient;
import com.google.cloud.storage.StorageOptions;
import com.google.cloud.pubsub.v1.Publisher;
import com.azure.storage.blob.BlobServiceClientBuilder;
import com.azure.messaging.servicebus.ServiceBusClientBuilder;

public class App {
    S3Client s3 = S3Client.create();
    SqsClient sqs = SqsClient.create();
}
