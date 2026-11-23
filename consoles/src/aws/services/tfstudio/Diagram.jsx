/* AWS skin of the shared layered diagram (common/infra-diagram): Terraform resource types -> layer / inbound-core-outbound, Region > VPC wrapper. */
import { useMemo } from "react";
import InfraDiagram from "../../../common/infra-diagram/InfraDiagram.jsx";

const ICON_FOR = { vpc: "vpc", s3: "s3", iam: "iam", lambda: "lambda", apigateway: "apigateway", rds: "rds", secretsmanager: "secretsmanager", cloudwatch: "cloudwatch", kms: "kms", sqs: "sqs", sns: "sns", dynamodb: "dynamodb", ec2: "ec2" };

export const AWS_PROFILE = {
  cloud: "aws",
  networkIcon: "vpc",
  hide: /^aws_vpc$/,
  primary: [
    ["edge", /^aws_(api_gateway|apigatewayv2|internet_gateway|nat_gateway|lb|alb|elb|security_group|network_acl|wafv2|cloudfront|route53|subnet|route_table|route\b|vpc_endpoint|eip|network_interface)/],
    ["data", /^aws_(db_|rds_|dynamodb|s3_|elasticache|docdb|neptune|redshift|efs|ebs)/],
    ["compute", /^aws_(lambda_|instance|launch_|autoscaling|ecs_|eks_|sfn_|sqs_|sns_|cloudwatch_event|kinesis|ecr_)/],
  ],
  fallback: [["data", /^aws_(secretsmanager_|kms_)/]],
  inbound: /^aws_(internet_gateway|security_group|network_acl|wafv2|lb_listener|lb_target|api_gateway_(resource|method|authorizer|api_key)|apigatewayv2_(route|authorizer)|lambda_(permission|event_source_mapping)|subnet|route_table|route\b|vpc_endpoint|eip|db_subnet_group|db_parameter_group|s3_bucket_(policy|public_access_block|ownership)|secretsmanager_secret(_version)?$)/,
  outbound: /^aws_(iam_|cloudwatch_log|api_gateway_integration|sns_topic_subscription|sqs_queue_policy|kms_)/,
  entry: /^aws_(api_gateway_rest_api|apigatewayv2_api|internet_gateway|lb|alb|elb|cloudfront_distribution)$/,
  iconOf: (n) => ICON_FOR[n.service] || n.service,
  typeLabel: (n) => n.type.replace(/^aws_/, ""),
};

export default function Diagram({ graph, selected, onSelect }) {
  const g = useMemo(() => ({ ...graph, wrappers: { region: `AWS Region · ${graph.region || "us-east-1"}`, network: graph.groups?.[0] ? { label: `VPC ${graph.groups[0].label}`, cidr: graph.groups[0].cidr } : { label: "VPC" } } }), [graph]);
  return <InfraDiagram graph={g} selected={selected} onSelect={onSelect} profile={AWS_PROFILE} />;
}
