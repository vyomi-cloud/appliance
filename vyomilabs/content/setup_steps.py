"""Console setup steps per cloud and layer. Each step names a REAL route in the v4 console (hash route), what to do there and the values to enter.
route=None means that service has no console view yet: the step then points at the CLI/SDK check instead and carries no screenshot.
Screenshots are captured from the live console by vyomilabs/content/capture_steps.mjs (never mocked up)."""


def s(title, route, do, fill=None, service=None, note=None, click=False):
    """click=True: the route is a list page, so the capture presses its Create button first to show the form."""
    return dict(title=title, route=route, do=do, fill=fill or {}, service=service or "", note=note or "", click=click)


STEPS = {
    "aws": {
        10: [s("Browse the model catalogue", "/bedrock/models", ["Open Bedrock, then Model catalog.", "Confirm a chat model and an embedding model are listed; you will use their ids in code."], service="Amazon Bedrock"),
             s("Try a chat in the playground", "/bedrock/playground", ["Open Playground, choose a chat model.", "Send: Reply with OK."], service="Amazon Bedrock")],
        3: [s("Create the AgentCore runtime", "/bedrock/agentcore", ["Open Bedrock AgentCore, Runtime, then create a runtime.", "Name it, point it at your agent code, keep the default network mode."], {"Name": "facilities-supervisor"}, "Bedrock AgentCore")],
        7: [s("Create the assets table", "/dynamodb/create-table", ["Open DynamoDB, Create table.", "Partition key is a string; keep on-demand capacity."], {"Table name": "assets", "Partition key": "asset_id"}, "Amazon DynamoDB"),
            s("Create the read-only tool", "/lambda/create/function", ["Open Lambda, Create function, Author from scratch.", "Runtime Python 3.12; paste the handler from the reference solution."], {"Function name": "asset-status"}, "AWS Lambda")],
        12: [s("Create the document bucket", "/s3/create", ["Open S3, Create bucket.", "Keep Block all public access on."], {"Bucket name": "facilities-docs"}, "Amazon S3"),
             s("Create the knowledge base", "/bedrock/knowledge-bases", ["Open Bedrock, Knowledge bases, Create.", "Choose the bucket as the data source and an embeddings model, then Sync."], {"Name": "facilities-kb"}, "Bedrock Knowledge Bases")],
        6: [s("Test retrieval on the knowledge base", "/bedrock/knowledge-bases", ["Open the knowledge base, Test.", "Ask: boiler pressure above 30 psi, and check the first source is the boiler SOP."], service="Bedrock Knowledge Bases")],
        11: [s("Create the guardrail", "/bedrock/guardrails", ["Open Bedrock, Guardrails, Create guardrail.", "Add a sensitive-information filter (email, phone) set to anonymise, on output."], {"Name": "facilities-guardrail"}, "Bedrock Guardrails")],
        9: [s("Create the memory", "/bedrock/agentcore", ["Open Bedrock AgentCore, Memory, Create memory.", "Enable the short-term events and a long-term strategy; set an expiry."], {"Name": "facilities-memory"}, "Bedrock AgentCore Memory")],
        4: [s("Create the gateway", "/bedrock/agentcore", ["Open Bedrock AgentCore, Gateways, Create gateway.", "Add your Lambda tools as targets."], {"Name": "facilities-gateway"}, "Bedrock AgentCore Gateway")],
        5: [s("Create the approval state machine", "/states/create", ["Open Step Functions, Create state machine.", "Use a task with the waitForTaskToken pattern that publishes to the approver topic."], {"Name": "work-order-approval"}, "AWS Step Functions"),
            s("Create the ledger table", "/dynamodb/create-table", ["Open DynamoDB, Create table."], {"Table name": "approval-ledger", "Partition key": "request_id"}, "Amazon DynamoDB"),
            s("Create the approver topic", "/sns/create-topic", ["Open SNS, Create topic, type Standard."], {"Name": "approver-inbox"}, "Amazon SNS"),
            s("Create the inbox queue", "/sqs/create-queue", ["Open SQS, Create queue, type Standard, then subscribe it to the topic."], {"Name": "approver-inbox-queue"}, "Amazon SQS")],
        1: [s("Create the user pool and WAF rule", None, ["The simulator has no console view for Cognito or WAF yet.", "Use the CLI commands under Quick validation to create and check them."], service="Amazon Cognito, AWS WAF",
              note="No console view yet: this layer is set up with the CLI.")],
        2: [s("Create the approver topic", "/sns/create-topic", ["Open SNS, Create topic."], {"Name": "approver-inbox"}, "Amazon SNS"),
            s("Review the guardrail", "/bedrock/guardrails", ["Open the guardrail from layer 11 and attach it to input as well."], service="Bedrock Guardrails")],
        8: [s("Create the log group", "/cloudwatch/logs/create", ["Open CloudWatch, Log groups, Create log group."], {"Log group name": "/facilities/agent"}, "Amazon CloudWatch")],
        13: [s("Create the ledger key", "/kms/create-key", ["Open KMS, Create key: symmetric, encrypt and decrypt.", "Give it an alias and turn on automatic rotation."], {"Alias": "facilities-ledger-key"}, "AWS KMS")],
    },
    "gcp": {
        10: [s("Browse Model Garden", "/vertex-ai/model-garden", ["Open Vertex AI, Model Garden.", "Confirm a chat model and an embedding model are listed (in-browser models on Nano, the Mesh pool on a Mesh)."], service="Vertex AI")],
        3: [s("Open the agent deployments", "/vertex-ai/deployments", ["Open Vertex AI, Agent Engine, deployments.", "Deploy facilities_supervisor from your agent code."], {"Name": "facilities_supervisor"}, "Vertex AI Agent Engine")],
        7: [s("Create the tool function", "/functions/create", ["Open Cloud Run functions, Create function.", "2nd gen, Python 3.12, HTTP trigger, paste the reference handler."], {"Function name": "asset-status"}, "Cloud Run functions"),
            s("Seed the assets", "/firestore", ["Open Firestore, Data.", "Add the assets collection and a few seed documents."], service="Firestore")],
        12: [s("Create the document bucket", "/storage/create-bucket", ["Open Cloud Storage, Create bucket.", "Keep public access prevention on."], {"Name": "facilities-docs"}, "Cloud Storage"),
             s("Create the RAG corpus", "/vertex-ai/rag-engine", ["Open Vertex AI, RAG Engine, Create corpus.", "Import the files from the bucket."], {"Name": "facilities-kb"}, "Vertex AI RAG Engine")],
        6: [s("Test retrieval on the corpus", "/vertex-ai/rag-engine", ["Open the corpus, then run a retrieval query.", "Ask: boiler pressure above 30 psi."], service="Vertex AI RAG Engine")],
        11: [s("Create the Model Armor template", None, ["The simulator has no console view for Model Armor yet.", "Create the template with the SDK, as in the reference solution."], service="Model Armor", note="No console view yet: this layer is set up with the SDK.")],
        9: [s("Create the memory bank", "/vertex-ai/memory-bank", ["Open Vertex AI, Memory Bank, Create."], {"Name": "facilities_memory"}, "Vertex AI Memory Bank")],
        4: [s("Create the gateway", "/vertex-ai/gateways", ["Open Agent Platform, Gateways, Create gateway.", "Attach the MCP tool server and the read-only policy."], {"Name": "facilities-gateway"}, "Agent Platform gateway")],
        5: [s("Create the approval topic", "/pubsub/topics/create", ["Open Pub/Sub, Create topic."], {"Topic ID": "work-order-approval"}, "Pub/Sub"),
            s("Create the inbox subscription", "/pubsub/subscriptions/create", ["Create a pull subscription on the topic."], {"Subscription ID": "approver-inbox"}, "Pub/Sub")],
        1: [s("Create the API gateway", "/apigateway/gateways/new", ["Open API Gateway, Create gateway.", "Choose your API config and the agent service account."], {"Gateway ID": "facilities-api-gw"}, "API Gateway")],
        2: [s("Create the approver topic", "/pubsub/topics/create", ["Open Pub/Sub, Create topic."], {"Topic ID": "work-order-approval"}, "Pub/Sub")],
        8: [s("Query the agent logs", "/logs/query", ["Open Logging, Logs Explorer.", "Filter on your agent's structured fields."], service="Cloud Logging")],
        13: [s("Create the key ring", "/security/kms/keyring/create", ["Open Key Management, Create key ring."], {"Key ring name": "facilities"}, "Cloud KMS"),
             s("Create the ledger key", "/security/kms/key/create", ["Create a symmetric key with a rotation period."], {"Key name": "ledger-key"}, "Cloud KMS")],
    },
    "azure": {
        10: [s("Create the Azure OpenAI resource", "/cognitiveservices/create", ["Open Azure AI services, Create.", "Pick OpenAI, then add the chat and embedding deployments."], {"Name": "facilities-openai"}, "Azure OpenAI")],
        3: [s("Create the container app", "/containerapps/create", ["Open Container Apps, Create.", "Create an environment, then deploy the supervisor image."], {"Container app name": "facilities-supervisor"}, "Azure Container Apps")],
        7: [s("Create the tools function app", "/functionapp/create", ["Open Function App, Create.", "Python 3.12, Consumption plan."], {"Function App name": "facilities-tools"}, "Azure Functions"),
            s("Create the storage account", "/storage/create", ["Open Storage accounts, Create.", "Add the assets and workorders tables."], {"Storage account name": "facilitiesdocs"}, "Azure Table storage")],
        12: [s("Create the document storage", "/storage/create", ["Open Storage accounts, Create.", "Add a docs container and upload the four SOPs."], {"Storage account name": "facilitiesdocs"}, "Blob Storage"),
             s("Open AI Search", "/aisearch", ["Open AI Search, then create the facilities-kb index and its indexer."], service="Azure AI Search")],
        6: [s("Query the search index", "/aisearch", ["Open the search service, Search explorer.", "Query: boiler pressure above 30 psi."], service="Azure AI Search")],
        11: [s("Review content safety", "/cognitiveservices", ["Open Azure AI services and add a Content Safety resource."], service="Azure AI Content Safety")],
        9: [s("Open Foundry threads", "/foundry", ["Open AI Foundry, Agents and Threads.", "Short-term memory is the thread; long-term facts go in a table."], service="Azure AI Foundry")],
        4: [s("Create API Management", "/apim/create", ["Open API Management, Create.", "Add the three tool operations and the policy expression."], {"Name": "facilities-apim"}, "API Management")],
        5: [s("Create the Service Bus namespace", "/servicebus/create", ["Open Service Bus, Create namespace.", "Add the work-order-approval topic and approver-inbox subscription."], {"Namespace name": "facilities-bus"}, "Azure Service Bus")],
        1: [s("Create API Management as the front door", "/apim/create", ["Open API Management, Create.", "Add a validate-jwt policy against Entra ID."], {"Name": "facilities-apim"}, "API Management"),
            s("Review Front Door and WAF", "/frontdoor", ["Open Front Door, add a WAF policy with managed rules."], service="Azure Front Door")],
        2: [s("Open the Service Bus inbox", "/servicebus", ["Open your namespace, the work-order-approval topic and the approver-inbox subscription."], service="Azure Service Bus")],
        8: [s("Create the Log Analytics workspace", "/loganalytics/create", ["Open Log Analytics, Create."], {"Name": "facilities-law"}, "Log Analytics"),
            s("Open Azure Monitor", "/monitor", ["Open Monitor, Metrics and Logs for your traces and the custom metric."], service="Azure Monitor")],
        13: [s("Create the key vault", "/keyvaults/create", ["Open Key vaults, Create.", "Add the ledger-key key and turn on rotation."], {"Key vault name": "facilities-kv"}, "Azure Key Vault")],
    },
}


_CLICK = {"Create the AgentCore runtime", "Create the knowledge base", "Create the guardrail", "Create the memory", "Create the gateway", "Open the agent deployments", "Create the RAG corpus", "Create the memory bank"}
for _c in STEPS.values():
    for _l in _c.values():
        for _st in _l:
            if _st["title"] in _CLICK:
                _st["click"] = True
