/* Declared gaps — products/features genuinely outside Vyomi's serverless-compute model:
 * SAM/CloudFormation "Applications", EC2-backed Lambda Capacity providers, AWS Signer code
 * signing, Firecracker MicroVMs + their Network connectors, Lambda@Edge Replicas, and the
 * Step Functions console cross-link. Each renders the REAL page title and an honest
 * "Not simulated in Vyomi" panel — never a disabled skeleton of the real page, per
 * consoles/AGENT-UI.md. (spec-map.json's honest_page flag covers every other element.) */
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { NotSimulatedContainer } from "../../kit/common.jsx";

function Honest({ title, feature, note }) {
  return (
    <ContentLayout header={<Header variant="h1">{title}</Header>}>
      <NotSimulatedContainer title={title} feature={feature} note={note} />
    </ContentLayout>
  );
}

export const Applications = () => <Honest title="Applications" feature="Lambda Applications (SAM / CloudFormation stacks)"
  note="Applications are CloudFormation/SAM stacks, not a Lambda resource — out of scope for the Lambda console; see the CloudFormation console." />;
export const CreateApplication = () => <Honest title="Create application" feature="Lambda Applications (SAM / CloudFormation stacks)"
  note="Applications are CloudFormation/SAM stacks, not a Lambda resource — out of scope for the Lambda console; see the CloudFormation console." />;

export const CapacityProviders = () => <Honest title="Capacity providers" feature="Lambda EC2 capacity providers"
  note="Capacity providers run functions on your own reserved EC2 instances instead of Lambda's serverless compute — Vyomi's Lambda core only has the serverless sandboxed runtime." />;
export const CreateCapacityProvider = () => <Honest title="Create capacity provider" feature="Lambda EC2 capacity providers"
  note="Capacity providers run functions on your own reserved EC2 instances instead of Lambda's serverless compute — Vyomi's Lambda core only has the serverless sandboxed runtime." />;

export const CodeSigningConfigurations = () => <Honest title="Code signing configurations" feature="Lambda code signing (AWS Signer integration)"
  note="Code signing configurations and signature-validation policies aren't modeled — see core/capabilities/aws/lambda.json (lambda.code-signing)." />;

export const MicrovmImages = () => <Honest title="MicroVM Images" feature="Lambda MicroVMs (Firecracker VM images)"
  note="MicroVMs are a dedicated Firecracker virtual-machine product layered on Lambda infrastructure — a different compute model from the sandboxed function runtime Vyomi simulates." />;
export const CreateMicrovmImage = () => <Honest title="Create MicroVM Image" feature="Lambda MicroVMs (Firecracker VM images)"
  note="MicroVMs are a dedicated Firecracker virtual-machine product layered on Lambda infrastructure — a different compute model from the sandboxed function runtime Vyomi simulates." />;
export const Microvms = () => <Honest title="MicroVMs" feature="Lambda MicroVMs (Firecracker VM images)"
  note="MicroVMs are a dedicated Firecracker virtual-machine product layered on Lambda infrastructure — a different compute model from the sandboxed function runtime Vyomi simulates." />;
export const RunMicrovm = () => <Honest title="Run MicroVM" feature="Lambda MicroVMs (Firecracker VM images)"
  note="MicroVMs are a dedicated Firecracker virtual-machine product layered on Lambda infrastructure — a different compute model from the sandboxed function runtime Vyomi simulates." />;

export const NetworkConnectors = () => <Honest title="Network connectors" feature="Lambda MicroVM network connectors"
  note="Network connectors bridge a MicroVM's compute type into a VPC — Vyomi doesn't model MicroVMs, so there's nothing for a connector to attach to." />;
export const CreateNetworkConnector = () => <Honest title="Create network connector" feature="Lambda MicroVM network connectors"
  note="Network connectors bridge a MicroVM's compute type into a VPC — Vyomi doesn't model MicroVMs, so there's nothing for a connector to attach to." />;

export const Replicas = () => <Honest title="Replicas" feature="Lambda@Edge function replicas"
  note="Replicas are Lambda@Edge copies of a function deployed to CloudFront edge locations — Vyomi has no CloudFront distribution to replicate into." />;

export const StepFunctionsStateMachines = () => <Honest title="Step Functions state machines" feature="AWS Step Functions"
  note="This page is a cross-link into the Step Functions console, not a Lambda resource. See the Step Functions console for real, stateful state machines (core/stepfunctions_core.py)." />;
