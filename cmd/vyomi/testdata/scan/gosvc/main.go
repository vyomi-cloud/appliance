package main

import (
	"cloud.google.com/go/pubsub"
	"cloud.google.com/go/storage"
	"github.com/Azure/azure-sdk-for-go/sdk/messaging/azservicebus"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

var (
	_ = s3.Client{}
	_ = dynamodb.Client{}
	_ = storage.Client{}
	_ = pubsub.Client{}
	_ = azblob.Client{}
	_ = azservicebus.Client{}
)
