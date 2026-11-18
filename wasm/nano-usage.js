/* Vyomi view-dwell telemetry for the Nano consoles (AWS / GCP / Azure): ONE shared script, cloud = data-cloud on its own <script> tag.
 *
 * One event = one visit to a console view: when it was entered, when it was left, and how long the visitor was actually ACTIVE on it
 * (hidden-tab time and time after 60 s without input are not counted). The portal turns these into "which views do people spend the
 * most time on" per cloud and per service.
 *
 * PRIVACY. What leaves the browser: {sid, cloud, view, service, enter, exit, dur}. `sid` is 16 random hex per browser TAB (sessionStorage),
 * not linkable across tabs/devices/people; the signed-in Nano cookie rides along (same origin) and the server hashes it, the client never
 * sends an email or id. `view`/`service` are the console's own ROUTE PATTERNS (e.g. "s3/buckets/:name", service "s3"), never the real URL,
 * so bucket/instance/user-typed names cannot leave the browser. No page titles, no query strings, no third-party calls.
 * OPT-OUT: nothing is sent when localStorage "vyomi.telemetry" === "off", navigator.doNotTrack is "1"/"yes", or window.VYOMI_NO_TELEMETRY is set.
 *
 * WIRE: POST same-origin /api/usage/views  {v:1, events:[{sid,cloud,view,service,enter,exit,dur}...]}  (<= 50 per request, expect 204).
 * Failures are dropped silently (no retry storm, no storage queue, no console noise). Timers start only after "vyomi-nano-ready" (or the
 * page load + 3 s) so the Pyodide boot is never slowed.
 *
 * The route table below is GENERATED from consoles/src/<cloud>/**: run `python3 scripts/gen_nano_usage_routes.py` after changing a route. */
(function () {
  "use strict";
  if (window.__vyUsage) return; window.__vyUsage = 1;

  /*ROUTES:BEGIN*/var ROUTES={"aws":["apigateway","apigateway/agentcore-targets","apigateway/api-keys","apigateway/api/:id","apigateway/apis","apigateway/apis/:id","apigateway/apis/:id/stages","apigateway/client-certificates","apigateway/create","apigateway/create-api-key","apigateway/create-http-api","apigateway/create-rest-api","apigateway/create-usage-plan","apigateway/create-websocket-api","apigateway/custom-domain-names","apigateway/domain-name-access-associations","apigateway/portal-products","apigateway/portals","apigateway/settings","apigateway/usage-plans","apigateway/vpc-links","backup","backup/create-plan","backup/jobs","backup/plans","backup/plans/view","backup/protected-resources","backup/restore-jobs","backup/vaults","backup/vaults/view","bedrock","bedrock/agentcore","bedrock/agentcore/gateways/:id","bedrock/agents","bedrock/agents/:id","bedrock/api-keys","bedrock/automated-reasoning","bedrock/compare-models","bedrock/custom-models/jobs/:id","bedrock/data-automation","bedrock/evaluations","bedrock/evaluations/:id","bedrock/flows","bedrock/flows/:id","bedrock/guardrails","bedrock/guardrails/:id","bedrock/imported-models/:id","bedrock/imported-models/jobs/:id","bedrock/knowledge-bases","bedrock/knowledge-bases/:id","bedrock/knowledge-bases/studio","bedrock/model-access","bedrock/models","bedrock/playground","bedrock/prompt-management","bedrock/prompt-management/:id","bedrock/prompt-optimization","bedrock/quickstart","bedrock/quotas","bedrock/settings","bedrock/tokenizer","cloudformation","cloudformation/create","cloudformation/exports","cloudformation/hooks/invocations","cloudformation/hooks/list","cloudformation/hooks/overview","cloudformation/iac-generator","cloudformation/registry/activated-extensions","cloudformation/registry/public-extensions","cloudformation/registry/public-extensions/resource-type/:name","cloudformation/registry/publisher","cloudformation/spotlight","cloudformation/stack-refactors","cloudformation/stacks","cloudformation/stacks/:name","cloudformation/stacks/:name/update","cloudformation/stacksets","cloudformation/template-studio","cloudwatch","cloudwatch/alarms","cloudwatch/alarms/:name","cloudwatch/alarms/create","cloudwatch/dashboards","cloudwatch/dashboards/:name","cloudwatch/dashboards/create","cloudwatch/home","cloudwatch/live-tail","cloudwatch/logs","cloudwatch/logs-insights","cloudwatch/logs/:name","cloudwatch/logs/:name/streams/:stream","cloudwatch/logs/:name/streams/create","cloudwatch/logs/create","cloudwatch/metrics","cloudwatch/settings","cost-explorer","dynamodb","dynamodb/backups","dynamodb/create-table","dynamodb/dashboard","dynamodb/dax/clusters","dynamodb/dax/events","dynamodb/dax/parameter-groups","dynamodb/dax/subnet-groups","dynamodb/explore","dynamodb/exports","dynamodb/exports/create","dynamodb/imports","dynamodb/imports/create","dynamodb/integrations","dynamodb/partiql","dynamodb/reserved-capacity","dynamodb/settings","dynamodb/settings/explore-items","dynamodb/settings/layout","dynamodb/tables","dynamodb/tables/:name","dynamodb/tables/:name/items","dynamodb/update-settings","ec2","ec2/allocate-elastic-ip","ec2/ami-catalog","ec2/amis","ec2/amis/:id","ec2/auto-scaling-groups","ec2/auto-scaling-groups/:id","ec2/capacity-manager","ec2/capacity-reservations","ec2/compare-security-group-rules","ec2/create-auto-scaling-group","ec2/create-iam-profile","ec2/create-key-pair","ec2/create-launch-template","ec2/create-lifecycle-policy","ec2/create-load-balancer","ec2/create-placement-group","ec2/create-security-group","ec2/create-snapshot","ec2/create-target-group","ec2/create-trust-store","ec2/create-volume","ec2/dashboard","ec2/dedicated-hosts","ec2/elastic-ips","ec2/events","ec2/home","ec2/image-builder","ec2/import-key-pair","ec2/instance-type-finder","ec2/instance-types","ec2/instance-types/:type","ec2/instances","ec2/instances/:id","ec2/instances/:id/create-image","ec2/key-pairs","ec2/launch-instance","ec2/launch-templates","ec2/lifecycle-manager","ec2/load-balancers","ec2/load-balancers/:id","ec2/migrate-a-server","ec2/network-interfaces","ec2/placement-groups","ec2/recycle-bin","ec2/reserved-instances","ec2/savings-plans","ec2/security-groups","ec2/security-groups/:id","ec2/security-groups/:id/edit-inbound-rules","ec2/security-groups/:id/edit-outbound-rules","ec2/settings","ec2/snapshots","ec2/spot-requests","ec2/target-groups","ec2/target-groups/:id","ec2/trust-stores","ec2/ultraservers","ec2/volumes","ec2/volumes/:id","ecr","ecr/registry","ecr/repositories","ecr/repositories/view","eks","eks/clusters","eks/clusters/view","eks/create","eventbridge","eventbridge/api-destinations","eventbridge/archives","eventbridge/archives/:name/edit","eventbridge/connections","eventbridge/create-api-destination","eventbridge/create-archive","eventbridge/create-connection","eventbridge/create-event-bus","eventbridge/create-global-endpoint","eventbridge/create-pipe","eventbridge/create-rule","eventbridge/create-schedule","eventbridge/create-scheduled-rule","eventbridge/dashboard","eventbridge/event-buses","eventbridge/event-buses/:name","eventbridge/event-buses/:name/edit","eventbridge/event-buses/:name/send","eventbridge/global-endpoints","eventbridge/home","eventbridge/partner-event-sources","eventbridge/pipes","eventbridge/pipes/:name","eventbridge/rules","eventbridge/rules/:name","eventbridge/rules/:name/edit","eventbridge/sandbox","eventbridge/schedule-groups","eventbridge/scheduled-rules","eventbridge/schedules","eventbridge/schemas","iam","iam/access-analyzer","iam/account-access-manager","iam/account-settings","iam/account-settings/assign-delegated-administrator","iam/account-settings/edit-password-policy","iam/analyzer-settings","iam/create-policy","iam/create-role","iam/create-user","iam/create-user-group","iam/credential-report","iam/dashboard","iam/groups","iam/groups/:name","iam/identity-providers","iam/identity-providers/:kind/:arn","iam/organization-activity","iam/policies","iam/policies/:name","iam/policy-simulator","iam/resource-analysis","iam/resource-control-policies","iam/resource-control-policies/:name","iam/roles","iam/roles/:name","iam/root-access-management","iam/security-credentials","iam/server-certificates","iam/service-control-policies","iam/service-control-policies/:name","iam/temporary-delegation-requests","iam/unused-access","iam/users","iam/users/:name","iam/users/:name/create-access-key","imagebuilder","imagebuilder/components","imagebuilder/components/view","imagebuilder/distributions","imagebuilder/images","imagebuilder/images/view","imagebuilder/infrastructure","imagebuilder/pipelines","imagebuilder/pipelines/view","imagebuilder/recipes","imagebuilder/recipes/view","kinesis","kinesis/home","kinesis/streams","kinesis/streams/:name","kinesis/streams/create","kms","kms/aws-managed-keys","kms/aws-managed-keys/:id","kms/cloudhsm-key-stores","kms/create-key","kms/customer-managed-keys","kms/customer-managed-keys/:id","kms/external-key-stores","kms/external-key-stores/create","kms/home","lambda","lambda/applications","lambda/capacity-providers","lambda/code-signing-configurations","lambda/create/application","lambda/create/capacity-provider","lambda/create/function","lambda/create/layer","lambda/create/microvm","lambda/create/microvm-image","lambda/create/network-connector","lambda/create/web-function","lambda/event-source-mappings","lambda/extensions","lambda/functions","lambda/functions/:name","lambda/functions/:name/add-trigger","lambda/functions/:name/create-alias","lambda/get-started","lambda/home","lambda/layers","lambda/microvm-images","lambda/microvms","lambda/network-connectors","lambda/replicas","lambda/statemachines","lambda/web-functions","networkmanager","networkmanager/global-networks","networkmanager/global-networks/view","rds","rds/automated-backups","rds/capacity-reservations","rds/certificate-update","rds/create-capacity-reservation","rds/create-database","rds/create-db-subnet-group","rds/create-parameter-group","rds/create-zero-etl-integration","rds/custom-engine-versions","rds/dashboard","rds/databases","rds/databases/:id","rds/event-subscriptions","rds/events","rds/exports-in-amazon-s3","rds/home","rds/option-groups","rds/parameter-groups","rds/parameter-groups/:name","rds/proxies","rds/query-editor","rds/recommendations","rds/reserved-instances","rds/restore-from-s3","rds/service-health","rds/service-quota","rds/snapshots","rds/subnet-groups","rds/take-snapshot","rds/zero-etl-integrations","s3","s3/access-analyzer","s3/access-grants","s3/access-points","s3/access-points-fsx","s3/batch-operations","s3/bucket/:bucket/create/folder","s3/bucket/:bucket/delete","s3/bucket/:bucket/empty","s3/buckets","s3/buckets/:name","s3/create","s3/directory-buckets","s3/file-systems","s3/get-started","s3/lens/dashboards","s3/lens/groups","s3/marketplace","s3/mrap","s3/object/:bucket","s3/olap","s3/settings","s3/table-buckets","s3/upload/:bucket","s3/vector-buckets","secretsmanager","secretsmanager/home","secretsmanager/listsecrets","secretsmanager/newsecret","secretsmanager/secret/:name","secretsmanager/secret/:name/delete","secretsmanager/secret/:name/edit-value","securityhub","securityhub/controls","securityhub/findings","securityhub/guardduty","sns","sns/create-subscription","sns/create-topic","sns/dashboard","sns/mobile/push-notifications","sns/mobile/text-messaging","sns/subscriptions","sns/subscriptions/:id","sns/topics","sns/topics/:name","sns/topics/:name/edit","sns/topics/:name/publish","sqs","sqs/create-queue","sqs/home","sqs/queues","sqs/queues/:name","sqs/queues/:name/delete","sqs/queues/:name/edit","sqs/queues/:name/purge","sqs/queues/:name/send-receive","ssm","ssm/associations","ssm/associations/:id","ssm/commands","ssm/commands/:id","ssm/create-association","ssm/create-document","ssm/create-maintenance-window","ssm/create-parameter","ssm/create-patch-baseline","ssm/documents","ssm/documents/view","ssm/maintenance-windows","ssm/maintenance-windows/:id","ssm/parameters","ssm/parameters/view","ssm/patch-baselines","ssm/patch-baselines/:id","ssm/run-command","states","states/activities","states/activities/:name","states/create","states/state-machines","states/state-machines/:name","states/state-machines/:name/start","vpc","vpc/all-resources","vpc/allocate-elastic-ip","vpc/client-vpn-endpoints","vpc/container-associations","vpc/create-internet-gateway","vpc/create-nat-gateway","vpc/create-route-table","vpc/create-security-group","vpc/create-subnet","vpc/create-vpc","vpc/customer-gateways","vpc/dashboard","vpc/dhcp-option-sets","vpc/dns-firewall-domain-lists","vpc/dns-firewall-rule-groups","vpc/domain-verifications","vpc/egress-only-internet-gateways","vpc/elastic-ips","vpc/encryption-control","vpc/endpoint-services","vpc/endpoints","vpc/firewall-policies","vpc/firewalls","vpc/home","vpc/internet-gateways","vpc/internet-gateways/:id","vpc/internet-gateways/:id/attach","vpc/lattice-services","vpc/lattice-services/:id","vpc/lattice-target-groups","vpc/lattice-target-groups/:id","vpc/managed-prefix-lists","vpc/metering-policies","vpc/mirror-filters","vpc/mirror-sessions","vpc/mirror-targets","vpc/nat-gateways","vpc/nat-gateways/:id","vpc/network-access-analyzer","vpc/network-acls","vpc/network-firewall-resource-groups","vpc/network-firewall-rule-groups","vpc/peering-connections","vpc/privatelink-getting-started","vpc/reachability-analyzer","vpc/reachability-analyzer/:id","vpc/resource-configurations","vpc/resource-gateways","vpc/route-servers","vpc/route-tables","vpc/route-tables/:id","vpc/route-tables/:id/edit-routes","vpc/security-groups","vpc/security-groups/:id","vpc/security-groups/:id/edit-inbound-rules","vpc/security-groups/:id/edit-outbound-rules","vpc/service-health","vpc/service-networks","vpc/service-networks/:id","vpc/settings","vpc/subnets","vpc/subnets/:id","vpc/tls-inspection-configurations","vpc/transit-gateway-attachments","vpc/transit-gateway-multicast","vpc/transit-gateway-policy-tables","vpc/transit-gateway-route-tables","vpc/transit-gateway-route-tables/:id","vpc/transit-gateways","vpc/verified-access-endpoints","vpc/verified-access-groups","vpc/verified-access-instances","vpc/verified-access-trust-providers","vpc/virtual-private-gateways","vpc/vpc-endpoint-associations","vpc/vpcs","vpc/vpcs/:id","vpc/vpcs/:id/edit-settings","vpc/vpn-concentrators","vpc/vpn-connections"],"gcp":["apigateway","apigateway/apis","apigateway/apis/:api","apigateway/apis/new","apigateway/gateways","apigateway/gateways/:region/:name","apigateway/gateways/new","apigateway/keys","artifacts","artifacts/create-repo","artifacts/repo/:location/:name","artifacts/repo/:location/:name/package/:pkg","artifacts/settings","backupdr","cloud-hub","cloudbuild","clouddeploy","clouddeploy/pipelines/:region/:name","cloudscheduler","cloudscheduler/jobs","cloudscheduler/jobs/:region/:name","cloudscheduler/jobs/:region/:name/edit","cloudscheduler/jobs/new","compute","compute/disks","compute/disks/create","compute/health-checks","compute/images","compute/instance-groups","compute/instance-templates","compute/instances","compute/instances/:zone/:name","compute/instances/create","compute/machine-images","compute/metadata","compute/operations","compute/overview","compute/settings","compute/snapshots","compute/zones","datastore","eventarc","eventarc/triggers","eventarc/triggers/:region/:name","eventarc/triggers/new","firestore","firestore/create-database","firestore/databases","firestore/databases/:name/create-index","firestore/databases/:name/disaster-recovery","firestore/databases/:name/import-export","firestore/databases/:name/indexes","firestore/databases/:name/insights","firestore/databases/:name/key-visualizer","firestore/databases/:name/rules","firestore/databases/:name/studio","firestore/databases/:name/ttl","firestore/databases/:name/usage","functions","functions/create","functions/detail/:region/:name","functions/domain-mappings","functions/jobs","functions/overview","functions/services","functions/worker-pools","iam-admin","iam-admin/analyzer","iam-admin/asset-inventory","iam-admin/audit","iam-admin/cloudidentity/consumer","iam-admin/essential-contacts","iam-admin/groups","iam-admin/iam","iam-admin/iam/deny","iam-admin/iam/grant-access","iam-admin/iam/log","iam-admin/iap","iam-admin/labels","iam-admin/managed-workload-identity-pools","iam-admin/orgpolicies","iam-admin/pam","iam-admin/principal-access-boundary","iam-admin/privacy","iam-admin/quotas","iam-admin/roles","iam-admin/roles/create","iam-admin/roles/details/:resource-name","iam-admin/security-insights","iam-admin/serviceaccounts","iam-admin/serviceaccounts/create","iam-admin/serviceaccounts/details/:resource-name","iam-admin/settings","iam-admin/tags","iam-admin/troubleshooter","iam-admin/workforce-identity-pools","iam-admin/workload-identity-pools","kubernetes","kubernetes/applications","kubernetes/backup","kubernetes/clusters","kubernetes/clusters/:location/:name","kubernetes/clusters/create","kubernetes/config","kubernetes/discovery","kubernetes/object-browser","kubernetes/overview","kubernetes/secrets-configmaps","kubernetes/storage","kubernetes/workloads","logs","logs/analytics","logs/metrics","logs/metrics/edit","logs/query","logs/router","logs/router/sink","logs/storage","logs/storage/bucket","logs/storage/bucket/:name","marketplace","memorystore","memorystore/create","memorystore/instances/:location/:id/configuration","memorystore/instances/:location/:id/connections","memorystore/instances/:location/:id/maintenance","memorystore/instances/:location/:id/nodes","memorystore/instances/:location/:id/overview","monitoring","monitoring/alerting","monitoring/alerting/alerts","monitoring/alerting/policies/create","monitoring/alerting/snooze/create","monitoring/application-monitoring","monitoring/cost-explorer","monitoring/dashboards","monitoring/dashboards/:id","monitoring/dashboards/create","monitoring/error-reporting","monitoring/groups","monitoring/integrations","monitoring/metrics-explorer","monitoring/metrics-management","monitoring/permissions","monitoring/services","monitoring/settings","monitoring/synthetic-monitoring","monitoring/trace-explorer","monitoring/uptime","monitoring/uptime/create","networking","networking/addresses/add","networking/addresses/list","networking/bring-your-own-ip","networking/connectivity-tests/add","networking/connectivity-tests/details/:name","networking/connectivity-tests/list","networking/firewall","networking/firewall/add","networking/internal-ranges","networking/networks/add","networking/networks/details/:name","networking/networks/list","networking/packet-mirroring","networking/routes/add","networking/routes/list","networking/serverless-vpc-access","networking/shared-vpc","networking/vpc-connectivity","networking/vpc-flow-logs","pubsub","pubsub/schemas","pubsub/snapshots","pubsub/subscriptions","pubsub/subscriptions/:name","pubsub/subscriptions/create","pubsub/topics","pubsub/topics/:name","pubsub/topics/:name/publish","pubsub/topics/create","resource-manager","resource-manager/create","run","run/create","run/detail/:region/:name","run/domains","run/jobs","run/jobs/create","run/jobs/details/:region/:name","run/overview","run/services","run/worker-pools","security/binauthz","security/kms","security/kms/autokey","security/kms/key-inventory","security/kms/key/create","security/kms/key/manage/:location/:keyring/:name","security/kms/keyring/create","security/kms/keyring/manage/:location/:name","security/kms/keyrings","security/scc","security/secret-manager","security/secret-manager/create","security/secret-manager/regional/:location/:name","security/secret-manager/secret/:name","sql","sql/backups","sql/create","sql/create/instance","sql/get-started","sql/instances/:name/backups","sql/instances/:name/connections","sql/instances/:name/databases","sql/instances/:name/databases/create","sql/instances/:name/operations","sql/instances/:name/overview","sql/instances/:name/query-insights","sql/instances/:name/replicas","sql/instances/:name/studio","sql/instances/:name/system-insights","sql/instances/:name/users","sql/instances/:name/users/add","storage","storage/advisor","storage/batch-operations","storage/browser","storage/browser/:name","storage/browser/:name/object","storage/create-bucket","storage/insights-datasets","storage/intelligence-configuration","storage/monitoring","storage/object-enrichments","storage/overview","storage/settings","vertex-ai","vertex-ai/adk","vertex-ai/agent-garden","vertex-ai/agent-registry","vertex-ai/agent-retrieval","vertex-ai/app-builder","vertex-ai/batch","vertex-ai/datasets","vertex-ai/deployments","vertex-ai/endpoints","vertex-ai/endpoints/:location/:id","vertex-ai/evaluation","vertex-ai/experiments","vertex-ai/feature-store","vertex-ai/gateways","vertex-ai/gateways/:location/:id","vertex-ai/mcp-servers","vertex-ai/memory-bank","vertex-ai/metadata","vertex-ai/model-garden","vertex-ai/model-garden/:publisher/:id","vertex-ai/models","vertex-ai/monitoring","vertex-ai/pipelines","vertex-ai/policies","vertex-ai/provisioned-throughput","vertex-ai/rag-engine","vertex-ai/search","vertex-ai/security","vertex-ai/sessions","vertex-ai/studio","vertex-ai/studio/prompt","vertex-ai/topology","vertex-ai/training","vertex-ai/tuning","vertex-ai/tuning/:location/:id","vertex-ai/tutorials","vertex-ai/vector-search","vertex-ai/workbench"],"azure":["acr","acr/:rg/:name","acr/:rg/:name/:panel","acr/create","aisearch","aisearch/:rg/:name","aisearch/:rg/:name/:panel","aks","aks/:rg/:name","aks/:rg/:name/:panel","aks/create","apim","apim/:rg/:name","apim/:rg/:name/:panel","apim/:rg/:name/apis/create","apim/:rg/:name/apis/create/:apitype","apim/create","appconfiguration","appconfiguration/:rg/:name","appconfiguration/:rg/:name/:panel","appconfiguration/create","appservices","appservices/:rg/:name","appservices/:rg/:name/:panel","appservices/create","cognitiveservices","cognitiveservices/:rg/:name","cognitiveservices/:rg/:name/:panel","cognitiveservices/create","cognitiveservices/deleted","containerapps","containerapps/:rg/:name","containerapps/:rg/:name/:panel","containerapps/create","containerapps/environments","containerapps/environments/:rg/:name","containerapps/environments/:rg/:name/:panel","containerapps/environments/create","containerapps/jobs","containerapps/jobs/:rg/:name","containerapps/jobs/:rg/:name/:panel","containerapps/jobs/create","cosmos","cosmos/:rg/:name","cosmos/:rg/:name/:panel","cosmos/create","cost","cost/advisor","cost/alertrules","cost/alerts","cost/allocation","cost/analysis","cost/budgets","cost/budgets/create","cost/changescope","cost/configuration","cost/diagnose","cost/exports","cost/invoices","cost/overview","cost/paymentmethods","cost/previewfeatures","cost/reservations","cost/savingsplans","cost/subscriptions","cost/support","defender","defender/:panel","defender/alerts","defender/alerts/:name","defender/attackpath","defender/automation","defender/compliance","defender/environment","defender/environment/:sub","defender/explorer","defender/inventory","defender/overview","defender/posture","defender/recommendations","defender/recommendations/:name","dns","dns/:rg/:name","dns/:rg/:name/:panel","dns/create","entra","entra/adminunits","entra/appregistrations","entra/appregistrations/:id","entra/appregistrations/:id/:panel","entra/appregistrations/register","entra/auditlogs","entra/customdomains","entra/customsecurityattributes","entra/devices","entra/enterpriseapps","entra/externalidentities","entra/groups","entra/groups/all","entra/groups/new","entra/licenses","entra/overview","entra/properties","entra/roles","entra/security","entra/signinlogs","entra/users","entra/users/:id","entra/users/:id/:panel","entra/users/create","entra/usersettings","eventgrid","eventgrid/domains","eventgrid/namespaces","eventgrid/partnerconfigurations","eventgrid/partnernamespaces","eventgrid/partnerregistrations","eventgrid/partnertopics","eventgrid/systemtopics","eventgrid/topics","eventgrid/topics/:rg/:name","eventgrid/topics/:rg/:name/:panel","eventgrid/topics/:rg/:name/subscriptions/create","eventgrid/topics/create","foundry","foundry/:panel","frontdoor","frontdoor/:rg/:name","frontdoor/:rg/:name/:panel","functionapp","functionapp/:rg/:name","functionapp/:rg/:name/:panel","functionapp/:rg/:name/functions/:fn","functionapp/:rg/:name/functions/create","functionapp/create","functionapp/create/:hosting","keyvaults","keyvaults/:rg/:name","keyvaults/:rg/:name/:panel","keyvaults/create","loganalytics","loganalytics/:rg/:name","loganalytics/:rg/:name/:panel","loganalytics/create","monitor","monitor/actiongroups","monitor/activitylog","monitor/advisor","monitor/alerts","monitor/autoscale","monitor/changeanalysis","monitor/createactiongroup","monitor/createalertrule","monitor/createautoscale","monitor/createdatacollectionendpoint","monitor/createdatacollectionrule","monitor/createloganalyticsworkspace","monitor/createprivatelinkscope","monitor/createworkbook","monitor/datacollectionendpoints","monitor/datacollectionrules","monitor/diagnosticsettings","monitor/diagnosticsettingsresource","monitor/grafanadashboards","monitor/healthmodels","monitor/insights-azurelocal","monitor/insightshub","monitor/issues","monitor/loganalyticsworkspaces","monitor/logs","monitor/managedgrafana","monitor/managedprometheus","monitor/metrics","monitor/monitoringcoverage","monitor/observabilityagents","monitor/overview","monitor/pipelines","monitor/privatelinkscoperesources","monitor/privatelinkscopes","monitor/scommanagedinstance","monitor/servicehealth","monitor/support","monitor/workbooks","networkmanagers","networkmanagers/:rg/:name","networkmanagers/:rg/:name/:panel","nsgs","nsgs/:rg/:name","nsgs/:rg/:name/:panel","nsgs/create","recoveryservices","recoveryservices/:rg/:name","recoveryservices/:rg/:name/:panel","resourcegroups","resourcegroups/:name","resourcegroups/:name/:panel","resourcegroups/:name/delete","resourcegroups/create","servicebus","servicebus/:rg/:name","servicebus/:rg/:name/:panel","servicebus/:rg/:name/queues/:queue","servicebus/:rg/:name/queues/:queue/:panel","servicebus/create","sql","sql/:rg/:server/:db","sql/:rg/:server/:db/:panel","sql/create","sql/servers/:rg/:server","sql/servers/:rg/:server/:panel","storage","storage/:rg/:name","storage/:rg/:name/:panel","storage/create","streamanalytics","streamanalytics/:rg/:name","streamanalytics/:rg/:name/:panel","subscriptions","subscriptions/:id","subscriptions/:id/:panel","subscriptions/create","vms","vms/:rg/:name","vms/:rg/:name/:panel","vms/create","vnets","vnets/:rg/:name","vnets/:rg/:name/:panel","vnets/create"]};/*ROUTES:END*/

  var me = document.currentScript, CLOUD = ((me && me.getAttribute("data-cloud")) || "").toLowerCase();
  if (CLOUD !== "aws" && CLOUD !== "gcp" && CLOUD !== "azure") {
    var m = /\/(aws|gcp|azure)(?:-console\.html|\/)/.exec((window.location && location.pathname) || ""); CLOUD = m ? m[1] : "";
  }
  if (!CLOUD) return;

  var URL_PATH = "/api/usage/views", FLUSH_MS = 30000, IDLE_MS = 60000, CAP_MS = 30 * 60000, MIN_MS = 1000, MAX_BATCH = 50, MAX_BUF = 200;
  var KEY_RE = /^[a-z0-9:_.\/-]{1,80}$/;
  var buf = [], cur = null, visible = !document.hidden, lastInput = 0, mark = 0, acc = 0, dead = false, started = false, flushT = null;

  function now() { return Date.now(); }
  function safe(fn) { return function () { try { return fn.apply(this, arguments); } catch (_) {} }; }

  function optedOut() {
    try { if (window.VYOMI_NO_TELEMETRY) return true; } catch (_) {}
    try { if (localStorage.getItem("vyomi.telemetry") === "off") return true; } catch (_) {}
    try { var d = navigator.doNotTrack; if (d === "1" || d === "yes") return true; } catch (_) {}
    return false;
  }

  /* per-TAB session id: random, lives in sessionStorage only */
  var SID = (function () {
    var k = "vyomi.usage.sid", v = "";
    try { v = sessionStorage.getItem(k) || ""; } catch (_) {}
    if (/^[0-9a-f]{16}$/.test(v)) return v;
    v = "";
    try { var a = new Uint8Array(8); (window.crypto || {}).getRandomValues(a); for (var i = 0; i < 8; i++) v += ("0" + a[i].toString(16)).slice(-2); } catch (_) { v = ""; }
    while (v.length < 16) v += Math.floor(Math.random() * 16).toString(16);
    try { sessionStorage.setItem(k, v); } catch (_) {}
    return v;
  })();

  /* ---- view key = the matched ROUTE PATTERN, never the real path ---- */
  var table = null;   // [{segs:[...], key, params}] grouped by length
  var firstSegs = {};
  function build() {
    table = {};
    (ROUTES[CLOUD] || []).forEach(function (p) {
      var segs = String(p).toLowerCase().split("/").filter(Boolean); if (!segs.length) return;
      var params = segs.filter(function (s) { return s.charAt(0) === ":"; }).length;
      (table[segs.length] = table[segs.length] || []).push({ segs: segs, key: segs.join("/"), params: params });
      firstSegs[segs[0]] = 1;
    });
    Object.keys(table).forEach(function (n) { table[n].sort(function (a, b) { return a.params - b.params; }); });   // most literal first
  }
  function viewFor(hash) {
    var h = String(hash == null ? (location.hash || "") : hash).replace(/^#/, "").split("?")[0];
    var parts = h.split("/").filter(Boolean).map(function (s) { var d = s; try { d = decodeURIComponent(s); } catch (_) {} return d.toLowerCase(); });
    if (!table) build();
    var hasRoutes = Object.keys(table).length > 0;
    if (!parts.length) { var isV4 = /\/v4\//.test((location.pathname || "")) || hasRoutes; return isV4 ? { view: "home", service: "home" } : { view: "classic", service: "classic" }; }
    var svc = parts[0];
    if (!firstSegs[svc]) return { view: "other", service: "other" };            // not a service we know: no free text, ever
    var cands = table[parts.length] || [];
    for (var i = 0; i < cands.length; i++) {
      var c = cands[i], ok = true;
      for (var j = 0; j < c.segs.length; j++) { if (c.segs[j].charAt(0) !== ":" && c.segs[j] !== parts[j]) { ok = false; break; } }
      if (ok) return finish(c.key, svc);
    }
    return finish(svc + "/other", svc);
  }
  function finish(view, svc) {
    view = String(view).slice(0, 80); svc = String(svc).slice(0, 80);
    return { view: KEY_RE.test(view) ? view : "other", service: KEY_RE.test(svc) ? svc : "other" };
  }

  /* ---- active-time accounting: counts only while the tab is visible AND the visitor was active in the last 60 s ---- */
  function account(t) {
    if (visible) { var end = Math.min(t, lastInput + IDLE_MS); if (end > mark) acc += end - mark; }
    mark = t;
  }
  function touch() { var t = now(); account(t); lastInput = t; mark = t; }

  function open(t) {
    var v = viewFor();
    cur = { view: v.view, service: v.service, enter: t };
    acc = 0; mark = t;
  }
  function close(t, reopen) {
    if (!cur) return;
    account(t);
    var dur = Math.min(Math.round(acc), CAP_MS);
    if (dur >= MIN_MS) {
      buf.push({ sid: SID, cloud: CLOUD, view: cur.view, service: cur.service, enter: cur.enter, exit: Math.round(t), dur: dur });
      if (buf.length > MAX_BUF) buf.splice(0, buf.length - MAX_BUF);
    }
    cur = null; acc = 0;
    if (reopen) open(t);
  }

  var onRoute = safe(function () {
    if (!started || dead) return;
    var t = now();
    if (cur) { var v = viewFor(); if (v.view === cur.view && v.service === cur.service) { touch(); return; } }   // same view type (other resource / query only): one visit
    close(t, false); touch(); if (visible) open(t);
  });
  var onVis = safe(function () {
    if (!started || dead) return;
    var t = now(), was = visible;
    if (was && document.hidden) { close(t, false); visible = false; flush(true); }
    else if (!was && !document.hidden) { visible = true; lastInput = t; mark = t; open(t); }
  });
  var onHide = safe(function () { if (!started) return; close(now(), false); flush(true); });

  /* ---- sending ---- */
  function send(events, unloading) {
    var body = JSON.stringify({ v: 1, events: events });
    if (unloading && navigator.sendBeacon) {
      try { if (navigator.sendBeacon(URL_PATH, new Blob([body], { type: "application/json" }))) return; } catch (_) {}
    }
    try {
      var p = fetch(URL_PATH, { method: "POST", credentials: "include", keepalive: true, headers: { "Content-Type": "application/json" }, body: body });
      if (p && p.then) p.then(function (r) { if (r && (r.status === 404 || r.status === 405 || r.status === 501)) stop(); }, function () {});
    } catch (_) {}
  }
  function flush(unloading) {
    if (dead || !buf.length) return;
    if (optedOut()) { buf.length = 0; return; }
    while (buf.length) send(buf.splice(0, MAX_BATCH), unloading);
  }
  function stop() { dead = true; buf.length = 0; if (flushT) { clearInterval(flushT); flushT = null; } }

  var tick = safe(function () {
    if (dead) return;
    if (optedOut()) { stop(); return; }
    var t = now();
    if (cur && visible) { account(t); if (acc >= CAP_MS) close(t, true); }   // a very long visit is cut into <=30 min events
    flush(false);
  });

  var start = safe(function () {
    if (started) return;
    if (optedOut()) return;
    if (!table) build();
    started = true;
    var t = now(); lastInput = t; mark = t; visible = !document.hidden;
    if (visible) open(t);
    ["mousemove", "keydown", "scroll", "click", "touchstart", "wheel"].forEach(function (e) { addEventListener(e, safe(touch), { passive: true, capture: true }); });
    addEventListener("hashchange", onRoute);
    addEventListener("popstate", onRoute);
    ["pushState", "replaceState"].forEach(function (m) {
      var orig = history[m]; if (typeof orig !== "function" || orig.__vyU) return;
      var w = function () { var r = orig.apply(this, arguments); onRoute(); return r; }; w.__vyU = 1; history[m] = w;
    });
    document.addEventListener("visibilitychange", onVis);
    addEventListener("pagehide", onHide);
    addEventListener("beforeunload", onHide);
    flushT = setInterval(tick, FLUSH_MS);
  });

  if (window.__vyNanoReady) start();
  else {
    addEventListener("vyomi-nano-ready", start, { once: true });
    var go = function () { setTimeout(start, 3000); };
    if (document.readyState === "complete") go(); else addEventListener("load", go, { once: true });
  }

  if (window.__VY_USAGE_DEBUG) window.__vyUsageDebug = { viewFor: viewFor, buf: buf, flush: flush, tick: tick, get cur() { return cur; }, get dead() { return dead; }, sid: SID };
})();
