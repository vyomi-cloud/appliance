# AWS / GCP / Azure service catalog

Generated 2026-10-26T14:24:51+00:00 from botocore 1.43.118, the Google API Discovery directory and Azure/azure-rest-api-specs. Build order: P1 → P2 → P3 (see `tests/conformance/expansion/priorities.json`). A service is **released** only after it passes the service gate (API, SDK, CLI, console UI offline + Nano, Java + Go + Playwright conformance) — see `tests/conformance/expansion/EXPANSION.md`.

| Cloud | Services upstream | Released in Vyomi | P1 to build | P2 to build |
|---|---|---|---|---|
| AWS | 435 | 12 | 16 | 17 |
| GCP | 316 | 11 | 12 | 12 |
| AZURE | 317 | 11 | 12 | 12 |

## P1

| Cloud | Service | Id | Operations | Status |
|---|---|---|---|---|
| AWS | AmazonApiGatewayV2 | `apigatewayv2` | 103 | not started |
| AWS | AWS CloudFormation | `cloudformation` | 90 | not started |
| AWS | Amazon CloudWatch | `cloudwatch` | 55 | not started |
| AWS | Amazon Cognito Identity Provider | `cognito-idp` | 132 | not started |
| AWS | Amazon Elastic Container Registry | `ecr` | 58 | not started |
| AWS | Amazon EC2 Container Service | `ecs` | 88 | not started |
| AWS | Amazon ElastiCache | `elasticache` | 77 | not started |
| AWS | Elastic Load Balancing | `elbv2` | 51 | not started |
| AWS | Amazon Kinesis | `kinesis` | 45 | not started |
| AWS | Amazon CloudWatch Logs | `logs` | 118 | not started |
| AWS | Amazon Route 53 | `route53` | 71 | not started |
| AWS | Amazon Simple Email Service | `sesv2` | 116 | not started |
| AWS | Amazon Simple Notification Service | `sns` | 42 | not started |
| AWS | Amazon Simple Systems Manager (SSM) | `ssm` | 152 | not started |
| AWS | AWS Step Functions | `stepfunctions` | 37 | not started |
| AWS | AWS Security Token Service | `sts` | 11 | not started |
| GCP | Artifact Registry API | `artifactregistry/v1` |  | not started |
| GCP | BigQuery API | `bigquery/v2` |  | not started |
| GCP | Cloud Scheduler API | `cloudscheduler/v1` |  | not started |
| GCP | Cloud Tasks API | `cloudtasks/v2` |  | not started |
| GCP | Kubernetes Engine API | `container/v1` |  | not started |
| GCP | Cloud DNS API | `dns/v1` |  | not started |
| GCP | IAM Service Account Credentials API | `iamcredentials/v1` |  | not started |
| GCP | Cloud Logging API | `logging/v2` |  | not started |
| GCP | Cloud Monitoring API | `monitoring/v3` |  | not started |
| GCP | Google Cloud Memorystore for Redis API | `redis/v1` |  | not started |
| GCP | Cloud Run Admin API | `run/v2` |  | not started |
| GCP | Workflows API | `workflows/v1` |  | not started |
| AZURE | app | `app` |  | not started |
| AZURE | appconfiguration | `appconfiguration` |  | not started |
| AZURE | applicationinsights | `applicationinsights` |  | not started |
| AZURE | cognitiveservices | `cognitiveservices` |  | not started |
| AZURE | containerregistry | `containerregistry` |  | not started |
| AZURE | containerservice | `containerservice` |  | not started |
| AZURE | dns | `dns` |  | not started |
| AZURE | eventhub | `eventhub` |  | not started |
| AZURE | monitor | `monitor` |  | not started |
| AZURE | msi | `msi` |  | not started |
| AZURE | operationalinsights | `operationalinsights` |  | not started |
| AZURE | redis | `redis` |  | not started |

## P2

| Cloud | Service | Id | Operations | Status |
|---|---|---|---|---|
| AWS | AWS Certificate Manager | `acm` | 40 | not started |
| AWS | AWS AppSync | `appsync` | 74 | not started |
| AWS | Amazon Athena | `athena` | 70 | not started |
| AWS | Auto Scaling | `autoscaling` | 68 | not started |
| AWS | AWS Backup | `backup` | 115 | not started |
| AWS | AWS Batch | `batch` | 48 | not started |
| AWS | Amazon Bedrock Runtime | `bedrock-runtime` | 11 | not started |
| AWS | AWS CodeBuild | `codebuild` | 59 | not started |
| AWS | Amazon DynamoDB Streams | `dynamodbstreams` | 4 | not started |
| AWS | Amazon Elastic File System | `efs` | 31 | not started |
| AWS | Amazon Kinesis Firehose | `firehose` | 12 | not started |
| AWS | AWS Glue | `glue` | 306 | not started |
| AWS | Managed Streaming for Kafka | `kafka` | 64 | not started |
| AWS | AmazonMQ | `mq` | 25 | not started |
| AWS | Amazon OpenSearch Service | `opensearch` | 96 | not started |
| AWS | Amazon EventBridge Scheduler | `scheduler` | 12 | not started |
| AWS | Amazon Simple Queue Service | `sqs` | 23 | released |
| AWS | AWS X-Ray | `xray` | 38 | not started |
| GCP | Agent Platform API | `aiplatform/v1` |  | not started |
| GCP | Batch API | `batch/v1` |  | not started |
| GCP | Cloud Bigtable Admin API | `bigtableadmin/v2` |  | not started |
| GCP | Certificate Manager API | `certificatemanager/v1` |  | not started |
| GCP | Cloud Trace API | `cloudtrace/v2` |  | not started |
| GCP | Cloud Composer API | `composer/v1` |  | not started |
| GCP | Dataflow API | `dataflow/v1b3` |  | not started |
| GCP | Cloud Dataproc API | `dataproc/v1` |  | not started |
| GCP | Cloud Datastore API | `datastore/v1` |  | not started |
| GCP | Cloud Filestore API | `file/v1` |  | not started |
| GCP | Cloud Spanner API | `spanner/v1` |  | not started |
| GCP | Cloud Translation API | `translate/v3` |  | not started |
| AZURE | batch | `batch` |  | not started |
| AZURE | cdn | `cdn` |  | not started |
| AZURE | datafactory | `datafactory` |  | not started |
| AZURE | frontdoor | `frontdoor` |  | not started |
| AZURE | mysql | `mysql` |  | not started |
| AZURE | notificationhubs | `notificationhubs` |  | not started |
| AZURE | postgresql | `postgresql` |  | not started |
| AZURE | privatedns | `privatedns` |  | not started |
| AZURE | search | `search` |  | not started |
| AZURE | servicefabric | `servicefabric` |  | not started |
| AZURE | signalr | `signalr` |  | not started |
| AZURE | synapse | `synapse` |  | not started |

## Released

| Cloud | Service | Id |
|---|---|---|
| AWS | apigateway | `apigateway` |
| AWS | Amazon DynamoDB | `dynamodb` |
| AWS | Amazon Elastic Compute Cloud | `ec2` |
| AWS | Amazon EventBridge | `events` |
| AWS | AWS Identity and Access Management | `iam` |
| AWS | AWS Key Management Service | `kms` |
| AWS | AWS Lambda | `lambda` |
| AWS | AWS RDS DataService | `rds-data` |
| AWS | Amazon Relational Database Service | `rds` |
| AWS | Amazon Simple Storage Service | `s3` |
| AWS | AWS Secrets Manager | `secretsmanager` |
| AWS | Amazon Simple Queue Service | `sqs` |
| GCP | API Gateway API | `apigateway/v1` |
| GCP | Cloud Functions API | `cloudfunctions/v2` |
| GCP | Cloud Key Management Service (KMS) API | `cloudkms/v1` |
| GCP | Compute Engine API | `compute/v1` |
| GCP | Eventarc API | `eventarc/v1` |
| GCP | Cloud Firestore API | `firestore/v1` |
| GCP | Identity and Access Management (IAM) API | `iam/v2` |
| GCP | Cloud Pub/Sub API | `pubsub/v1` |
| GCP | Secret Manager API | `secretmanager/v1` |
| GCP | Cloud SQL Admin API | `sqladmin/v1` |
| GCP | Cloud Storage API | `storage/v1` |
| AZURE | apimanagement | `apimanagement` |
| AZURE | authorization | `authorization` |
| AZURE | compute | `compute` |
| AZURE | cosmos-db | `cosmos-db` |
| AZURE | eventgrid | `eventgrid` |
| AZURE | keyvault | `keyvault` |
| AZURE | network | `network` |
| AZURE | servicebus | `servicebus` |
| AZURE | sql | `sql` |
| AZURE | storage | `storage` |
| AZURE | web | `web` |

## P3 (everything else)

<details><summary>AWS — 390</summary>

`accessanalyzer`, `account-access`, `account`, `acm-pca`, `agent-registry-control`, `agent-registry`, `aiops`, `amp`, `amplify`, `amplifybackend`, `amplifyuibuilder`, `apigatewaymanagementapi`, `appconfig`, `appconfigdata`, `appfabric`, `appflow`, `appintegrations`, `application-autoscaling`, `application-insights`, `application-signals`, `applicationcostprofiler`, `appmesh`, `apprunner`, `appstream`, `arc-region-switch`, `arc-zonal-shift`, `artifact`, `auditmanager`, `autoscaling-plans`, `b2bi`, `backup-gateway`, `backupsearch`, `bcm-dashboards`, `bcm-data-exports`, `bcm-pricing-calculator`, `bcm-recommended-actions`, `bedrock-agent-runtime`, `bedrock-agent`, `bedrock-agentcore-control`, `bedrock-agentcore`, `bedrock-data-automation-runtime`, `bedrock-data-automation`, `bedrock`, `billing`, `billingconductor`, `braket`, `budgets`, `ce`, `chatbot`, `chime-sdk-identity`, `chime-sdk-media-pipelines`, `chime-sdk-meetings`, `chime-sdk-messaging`, `chime-sdk-voice`, `chime`, `cleanrooms`, `cleanroomsml`, `cloud9`, `cloudcontrol`, `clouddirectory`, `cloudfront-keyvaluestore`, `cloudfront`, `cloudhsm`, `cloudhsmv2`, `cloudsearch`, `cloudsearchdomain`, `cloudtrail-data`, `cloudtrail`, `cloudwatchomni`, `codeartifact`, `codecatalyst`, `codecommit`, `codeconnections`, `codedeploy`, `codeguru-reviewer`, `codeguru-security`, `codeguruprofiler`, `codepipeline`, `codestar-connections`, `codestar-notifications`, `cognito-identity`, `cognito-sync`, `comprehend`, `comprehendmedical`, `compute-optimizer-automation`, `compute-optimizer`, `config`, `connect-contact-lens`, `connect`, `connectcampaigns`, `connectcampaignsv2`, `connectcases`, `connecthealth`, `connectparticipant`, `continuum`, `controlcatalog`, `controltower`, `cost-optimization-hub`, `cur`, `customer-profiles`, `databrew`, `dataexchange`, `datapipeline`, `datasync`, `datazone`, `dax`, `deadline`, `detective`, `devicefarm`, `devops-agent`, `devops-guru`, `directconnect`, `discovery`, `dlm`, `dms`, `docdb-elastic`, `docdb`, `drs`, `ds-data`, `ds`, `dsql`, `ebs`, `ec2-instance-connect`, `ecr-public`, `eks-auth`, `eks`, `elasticbeanstalk`, `elb`, `elementalinference`, `emr-containers`, `emr-serverless`, `emr`, `endusermessaging`, `entityresolution`, `es`, `eventbridgev2`, `evs`, `fis`, `fms`, `forecast`, `forecastquery`, `frauddetector`, `freetier`, `fsx`, `gamelift`, `gameliftstreams`, `geo-maps`, `geo-places`, `geo-routes`, `glacier`, `globalaccelerator`, `grafana`, `greengrass`, `greengrassv2`, `groundstation`, `guardduty`, `health`, `healthlake`, `iam-toolbox`, `identitystore`, `imagebuilder`, `importexport`, `inspector-scan`, `inspector`, `inspector2`, `interconnect`, `internetmonitor`, `invoicing`, `iot-data`, `iot-jobs-data`, `iot-managed-integrations`, `iot`, `iotdeviceadvisor`, `iotfleetwise`, `iotsecuretunneling`, `iotsitewise`, `iotthingsgraph`, `iottwinmaker`, `iotwireless`, `ivs-realtime`, `ivs`, `ivschat`, `kafkaconnect`, `kendra-ranking`, `kendra`, `keyspaces`, `keyspacesstreams`, `kinesis-video-archived-media`, `kinesis-video-media`, `kinesis-video-signaling`, `kinesis-video-webrtc-storage`, `kinesisanalytics`, `kinesisanalyticsv2`, `kinesisvideo`, `lakeformation`, `lambda-core`, `lambda-microvms`, `lambda-web`, `launch-wizard`, `lex-models`, `lex-runtime`, `lexv2-models`, `lexv2-runtime`, `license-manager-linux-subscriptions`, `license-manager-user-subscriptions`, `license-manager`, `lightsail`, `location`, `lookoutequipment`, `m2`, `machinelearning`, `macie2`, `mailmanager`, `managedblockchain-query`, `managedblockchain`, `marketplace-agreement`, `marketplace-catalog`, `marketplace-deployment`, `marketplace-discovery`, `marketplace-entitlement`, `marketplace-reporting`, `marketplacecommerceanalytics`, `mediaconnect`, `mediaconvert`, `medialive`, `mediapackage-vod`, `mediapackage`, `mediapackagev2`, `mediastore-data`, `mediastore`, `mediatailor`, `medical-imaging`, `memorydb`, `meteringmarketplace`, `mgh`, `mgn`, `migration-hub-refactor-spaces`, `migrationhub-config`, `migrationhuborchestrator`, `migrationhubstrategy`, `mpa`, `mturk`, `mwaa-serverless`, `mwaa`, `neptune-graph`, `neptune`, `neptunedata`, `network-firewall`, `network-security-manager`, `networkflowmonitor`, `networkmanager`, `networkmonitor`, `notifications`, `notificationscontacts`, `nova-act`, `oam`, `observabilityadmin`, `odb`, `omics`, `opensearchserverless`, `organizations`, `osis`, `outposts`, `partnercentral-account`, `partnercentral-benefits`, `partnercentral-channel`, `partnercentral-revenue-measurement`, `partnercentral-selling`, `payment-cryptography-data`, `payment-cryptography`, `pca-connector-ad`, `pca-connector-scep`, `pcs`, `personalize-events`, `personalize-runtime`, `personalize`, `pi`, `pinpoint-email`, `pinpoint-sms-voice-v2`, `pinpoint-sms-voice`, `pinpoint`, `pipes`, `polly`, `pricing-plan-manager`, `pricing`, `proton`, `qapps`, `qbusiness`, `qconnect`, `quicksight`, `ram`, `rbin`, `redshift-data`, `redshift-serverless`, `redshift`, `rekognition`, `repostspace`, `resiliencehub`, `resiliencehubv2`, `resource-explorer-2`, `resource-groups`, `resourcegroupstaggingapi`, `rolesanywhere`, `route53-recovery-cluster`, `route53-recovery-control-config`, `route53-recovery-readiness`, `route53domains`, `route53globalresolver`, `route53profiles`, `route53resolver`, `rtbfabric`, `rum`, `s3control`, `s3files`, `s3outposts`, `s3tables`, `s3vectors`, `sagemaker-a2i-runtime`, `sagemaker-edge`, `sagemaker-featurestore-runtime`, `sagemaker-geospatial`, `sagemaker-metrics`, `sagemaker-runtime`, `sagemaker`, `sagemakerjobruntime`, `sagemakertrainingsessionruntime`, `savingsplans`, `schemas`, `sdb`, `security-ir`, `securityagent`, `securityhub`, `securitylake`, `serverlessrepo`, `service-quotas`, `servicecatalog-appregistry`, `servicecatalog`, `servicediscovery`, `ses`, `shield`, `signer-data`, `signer`, `signin`, `simpledbv2`, `sms-voice`, `snow-device-management`, `snowball`, `socialmessaging`, `ssm-contacts`, `ssm-guiconnect`, `ssm-incidents`, `ssm-quicksetup`, `ssm-sap`, `sso-admin`, `sso-oidc`, `sso`, `storagegateway`, `supplychain`, `support-app`, `support`, `supportauthz`, `sustainability`, `swf`, `synthetics`, `taxsettings`, `textract`, `timestream-influxdb`, `timestream-query`, `timestream-write`, `transcribe`, `transfer`, `translate`, `trustedadvisor`, `uxc`, `verifiedpermissions`, `voice-id`, `vpc-lattice`, `waf-regional`, `waf`, `wafv2`, `wellarchitected`, `wickr`, `wisdom`, `workdocs`, `workmail`, `workmailmessageflow`, `workspaces-instances`, `workspaces-thin-client`, `workspaces-web`, `workspaces`

</details>

<details><summary>GCP — 281</summary>

`abusiveexperiencereport/v1`, `acceleratedmobilepageurl/v1`, `accessapproval/v1`, `accesscontextmanager/v1`, `addressvalidation/v1`, `adexchangebuyer2/v2beta1`, `adexperiencereport/v1`, `admin/reports_v1`, `admob/v1`, `adsense/v2`, `adsenseplatform/v1`, `advisorynotifications/v1`, `agenciesandbrands/v1`, `agentidentity/v1`, `agentidentitycredentials/v1`, `agentregistry/v1`, `airquality/v1`, `alertcenter/v1beta1`, `alloydb/v1`, `analyticsadmin/v1beta`, `analyticsdata/v1beta`, `analyticshub/v1`, `androiddeveloperidstatus/v1`, `androiddeviceprovisioning/v1`, `androidenterprise/v1`, `androidmanagement/v1`, `androidpublisher/v3`, `apigee/v1`, `apihub/v1`, `apikeys/v2`, `apim/v1alpha`, `appengine/v1`, `apphub/v1`, `appsmarket/v2`, `area120tables/v1alpha1`, `areainsights/v1`, `assuredworkloads/v1`, `auditmanager/v1`, `authorizedbuyersmarketplace/v1`, `backupdr/v1`, `baremetalsolution/v2`, `beyondcorp/v1`, `biglake/v1`, `bigqueryconnection/v1`, `bigquerydatapolicy/v2`, `bigquerydatatransfer/v1`, `bigqueryreservation/v1`, `billingbudgets/v1`, `binaryauthorization/v1`, `blockchainnodeengine/v1`, `blogger/v3`, `books/v1`, `businessprofileperformance/v1`, `calendar/v3`, `ces/v1`, `chat/v1`, `checks/v1alpha`, `chromemanagement/v1`, `chromepolicy/v1`, `chromeuxreport/v1`, `chromewebstore/v2`, `civicinfo/v2`, `classroom/v1`, `cloudasset/v1`, `cloudbilling/v1`, `cloudbuild/v2`, `cloudchannel/v1`, `cloudcommerceprocurement/v1`, `cloudcontrolspartner/v1`, `clouddeploy/v1`, `clouderrorreporting/v1beta1`, `cloudidentity/v1`, `cloudlocationfinder/v1`, `cloudnumberregistry/v1alpha`, `cloudproductregistry/v1`, `cloudprofiler/v2`, `cloudresourcemanager/v3`, `cloudsearch/v1`, `cloudshell/v1`, `cloudsupport/v2`, `config/v1`, `connectors/v2`, `contactcenteraiplatform/v1alpha1`, `contactcenterinsights/v1`, `containeranalysis/v1`, `contentwarehouse/v1`, `css/v1`, `curationpartners/v1`, `customsearch/v1`, `databasecenter/v1beta`, `datacatalog/v1`, `dataform/v1`, `datafusion/v1`, `datalabeling/v1beta1`, `datalineage/v1`, `datamanager/v1`, `datamigration/v1`, `datapipelines/v1`, `dataplex/v1`, `dataportability/v1`, `datastream/v1`, `deepreview/v1`, `deploymentmanager/v2`, `developerconnect/v1`, `developerknowledge/v1`, `devicerun/v1alpha`, `dfareporting/v5`, `dialogflow/v3`, `digitalassetlinks/v1`, `discovery/v1`, `discoveryengine/v1`, `displayvideo/v5`, `dlp/v2`, `docs/v1`, `documentai/v1`, `domains/v1`, `doubleclickbidmanager/v2`, `doubleclicksearch/v2`, `drive/v3`, `driveactivity/v2`, `drivelabels/v2`, `essentialcontacts/v1`, `factchecktools/v1alpha1`, `fcm/v1`, `fcmdata/v1beta1`, `firebase/v1beta1`, `firebaseappcheck/v1`, `firebaseappdistribution/v1`, `firebaseapphosting/v1`, `firebasecrashlytics/v1alpha`, `firebasedatabase/v1beta`, `firebasedataconnect/v1`, `firebasedynamiclinks/v1`, `firebasehosting/v1`, `firebaseml/v1`, `firebaserules/v1`, `firebasestorage/v1beta`, `fitness/v1`, `forms/v1`, `ftp/v1`, `games/v1`, `gamesConfiguration/v1configuration`, `gamesManagement/v1management`, `gkebackup/v1`, `gkehub/v2`, `gkeonprem/v1`, `gmail/v1`, `gmailpostmastertools/v2`, `groupsmigration/v1`, `groupssettings/v1`, `health/v4`, `healthcare/v1`, `homegraph/v1`, `hypercomputecluster/v1`, `iap/v1`, `identitytoolkit/v3`, `ids/v1`, `indexing/v3`, `integrations/v2`, `jobs/v4`, `keep/v1`, `kgsearch/v1`, `kmsinventory/v1`, `language/v2`, `libraryagent/v1`, `licensing/v1`, `localservices/v1`, `looker/v1`, `managedidentities/v1`, `managedkafka/v1`, `manufacturers/v1`, `marketingplatformadmin/v1alpha`, `meet/v2`, `memcache/v1`, `merchantapi/reviews_v1beta`, `metastore/v1`, `migrationcenter/v1`, `ml/v1`, `mybusinessaccountmanagement/v1`, `mybusinessbusinessinformation/v1`, `mybusinesslodging/v1`, `mybusinessnotifications/v1`, `mybusinessplaceactions/v1`, `mybusinessqanda/v1`, `mybusinessverifications/v1`, `netapp/v1`, `networkconnectivity/v1`, `networkmanagement/v1`, `networksecurity/v1`, `networkservices/v1`, `notebooks/v2`, `oauth2/v2`, `observability/v1`, `ondemandscanning/v1`, `oracledatabase/v1`, `orgpolicy/v2`, `osconfig/v2`, `oslogin/v1`, `pagespeedonline/v5`, `parallelstore/v1`, `parametermanager/v1`, `paymentsresellersubscription/v1`, `people/v1`, `places/v1`, `playcustomapp/v1`, `playdeveloperreporting/v1beta1`, `playgrouping/v1alpha1`, `playintegrity/v1`, `policyanalyzer/v1`, `policysimulator/v1`, `policytroubleshooter/v3`, `pollen/v1`, `poly/v1`, `privateca/v1`, `prod_tt_sasportal/v1alpha1`, `publicca/v1`, `pubsublite/v1`, `rapidmigrationassessment/v1`, `readerrevenuesubscriptionlinking/v1`, `realtimebidding/v1`, `recaptchaenterprise/v1`, `recommendationengine/v1beta1`, `recommender/v1`, `reseller/v1`, `retail/v2`, `runtimeconfig/v1`, `saasservicemgmt/v1`, `safebrowsing/v5`, `sasportal/v1alpha1`, `script/v1`, `searchads360/v23`, `searchconsole/v1`, `securesourcemanager/v1`, `securitycenter/v1`, `securityposture/v1`, `serviceconsumermanagement/v1`, `servicecontrol/v2`, `servicedirectory/v1`, `servicemanagement/v1`, `servicenetworking/v1`, `serviceusage/v1`, `sheets/v4`, `siteVerification/v1`, `slides/v1`, `smartdevicemanagement/v1`, `solar/v1`, `speech/v1`, `storagebatchoperations/v1`, `storagetransfer/v1`, `streetviewpublish/v1`, `sts/v1`, `tagmanager/v2`, `tasks/v1`, `testing/v1`, `texttospeech/v1`, `threatintelligence/v1beta`, `toolresults/v1beta3`, `tpu/v2`, `trafficdirector/v3`, `transcoder/v1`, `travelimpactmodel/v1`, `vault/v1`, `verifiedaccess/v2`, `versionhistory/v1`, `videointelligence/v1`, `vision/v1`, `vmmigration/v1`, `vmwareengine/v1`, `vpcaccess/v1`, `walletobjects/v1`, `webcontentpublisher/v1`, `webfonts/v1`, `webrisk/v1`, `websecurityscanner/v1`, `workflowexecutions/v1`, `workloadmanager/v1`, `workspaceevents/v1`, `workstations/v1`, `youtube/v3`, `youtubeAnalytics/v2`, `youtubereporting/v1`

</details>

<details><summary>AZURE — 282</summary>

`EnterpriseKnowledgeGraph`, `addons`, `adhybridhealthservice`, `advisor`, `agricultureplatform`, `agrifood`, `ai-foundry`, `ai`, `alertsmanagement`, `analysisservices`, `anyscale`, `apicenter`, `appcomplianceautomation`, `applink`, `appplatform`, `artifactsigning`, `attestation`, `automanage`, `automation`, `awsconnector`, `azsadmin`, `azure-kusto`, `azure-native-integrations`, `azureactivedirectory`, `azurearcdata`, `azuredata`, `azuredatatransfer`, `azuredependencymap`, `azurefleet`, `azureintegrationspaces`, `azurelargeinstance`, `azureresiliencemanagement`, `azurestack`, `azurestackhci`, `baremetalinfrastructure`, `billing`, `billingbenefits`, `billingtrust`, `blueprint`, `botservice`, `carbon`, `certificateregistration`, `chaos`, `cloudhealth`, `cloudshell`, `codesigning`, `commerce`, `common-types`, `communication`, `communitytraining`, `computebulkactions`, `computelimit`, `computeschedule`, `confidentialledger`, `confluent`, `connectedcache`, `connectedvmware`, `consumption`, `containerinstance`, `containerstorage`, `contosowidgetmanager`, `cost-management`, `cpim`, `customer-insights`, `customerlockbox`, `customproviders`, `dashboard`, `databasefleetmanager`, `databasewatcher`, `databox`, `databoxedge`, `databricks`, `datacatalog`, `datadog`, `datalake-analytics`, `datalake-store`, `datamigration`, `dataprotection`, `datashare`, `dell`, `desktopvirtualization`, `devcenter`, `developerhub`, `deviceprovisioningservices`, `deviceregistry`, `deviceupdate`, `devops`, `devopsinfrastructure`, `devspaces`, `devtestlabs`, `dfp`, `digitaltwins`, `discovery`, `dnc`, `dnsresolver`, `domainregistration`, `domainservices`, `durabletask`, `dynamicstelemetry`, `dynatrace`, `edge`, `edgemarketplace`, `edgeoperator`, `edgeorder`, `edgeorderpartner`, `edgezones`, `education`, `elastic`, `elasticsan`, `engagementfabric`, `ews`, `extendedlocation`, `fabric`, `fileshares`, `fist`, `fluidrelay`, `gcpconnector`, `github-network`, `graphservicesprod`, `guestconfiguration`, `hanaonazure`, `hardwaresecuritymodules`, `hdinsight`, `healthbot`, `healthcareapis`, `healthdataaiservices`, `help`, `horizondb`, `hybridaks`, `hybridcloud`, `hybridcompute`, `hybridconnectivity`, `hybridkubernetes`, `hybridnetwork`, `imagebuilder`, `imds`, `impact`, `inferenceservice`, `informatica`, `intune`, `iotcentral`, `iothub`, `iotoperations`, `iotoperationsdataprocessor`, `iotoperationsmq`, `iotoperationsorchestrator`, `iotspaces`, `kubernetesconfiguration`, `kubernetesruntime`, `labservices`, `liftrarize`, `liftrcommvault`, `liftrhyperexecute`, `liftrmongodb`, `liftrpinecone`, `liftrqumulo`, `liftrweightsandbiases`, `loadtestservice`, `logic`, `m365securityandcompliance`, `machinelearning`, `machinelearningservices`, `maintenance`, `managednetwork`, `managednetworkfabric`, `managedoperations`, `managedservices`, `management`, `managementpartner`, `manufacturingplatform`, `maps`, `mariadb`, `marketplace`, `marketplacecatalog`, `marketplacenotifications`, `marketplaceordering`, `migrate`, `migrateprojects`, `mission`, `mongocluster`, `monitoringservice`, `mysqldiscovery`, `napster`, `netapp`, `networkcloud`, `networkfunction`, `newrelic`, `nginx`, `oep`, `offazurespringboot`, `onlineexperimentation`, `operationsmanagement`, `oracle`, `orbital`, `orbitalplanetarycomputer`, `paloaltonetworks`, `peering`, `platformvalidation`, `playwrighttesting`, `policyinsights`, `portal`, `portalservices`, `postgresqlhsc`, `powerbidedicated`, `powerbiembedded`, `powerbiprivatelinks`, `powerplatform`, `privatetrafficmanager`, `professionalservice`, `programenrollment`, `programmableconnectivity`, `providerhub`, `purestorage`, `purview`, `purviewdatagovernace`, `purviewdatagovernance`, `purviewpolicy`, `quantum`, `quota`, `recommendationsservice`, `recoveryservices`, `recoveryservicesbackup`, `recoveryservicesdatareplication`, `recoveryservicessiterecovery`, `redhatopenshift`, `redisenterprise`, `relationships`, `relay`, `reservations`, `resourceconnector`, `resourcegraph`, `resourcehealth`, `resourcemover`, `resources`, `riskiq`, `saas`, `scheduler`, `schemaregistry`, `scom`, `scvmm`, `security`, `securityandcompliance`, `securityinsights`, `serialconsole`, `service-map`, `servicefabricmanagedclusters`, `servicefabricmesh`, `servicelinker`, `servicenetworking`, `softwareplan`, `solutions`, `sovereign`, `sphere`, `splitio`, `sqlvirtualmachine`, `standbypool`, `storageactions`, `storagecache`, `storagediscovery`, `storageimportexport`, `storagemover`, `storagepool`, `storagesync`, `streamanalytics`, `subscription`, `support`, `syntex`, `terraform`, `testbase`, `timeseriesinsights`, `trafficmanager`, `translation`, `verifiedid`, `vi`, `vmware`, `vmwarecloudsimple`, `webpubsub`, `widget`, `windowsesu`, `windowsiot`, `workloadmonitor`, `workloads`

</details>

