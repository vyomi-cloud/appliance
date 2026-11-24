import boto3

sns, sqs, lam = boto3.client("sns"), boto3.client("sqs"), boto3.client("lambda")
topic = sns.create_topic(Name="approver-inbox")["TopicArn"]
qurl = sqs.create_queue(QueueName="approver-inbox-queue")["QueueUrl"]
qarn = sqs.get_queue_attributes(QueueUrl=qurl, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=qarn)

env = lam.get_function_configuration(FunctionName="facilities-request-approval")["Environment"]["Variables"]
env["INBOX_TOPIC_ARN"] = topic
lam.update_function_configuration(FunctionName="facilities-request-approval", Environment={"Variables": env})
print("topic", topic)
print("queue", qurl)
print("request-approval now publishes to the inbox")
