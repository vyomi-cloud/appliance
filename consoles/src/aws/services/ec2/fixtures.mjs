/* UI-conformance fixtures for EC2 (native EC2 Query protocol: form-encoded Action=..., XML
 * response). Standalone (no import from api.js / wire.js — those touch browser globals that
 * don't exist under the Node harness). See s3/fixtures.mjs for the shared contract. */

function flatten(value, prefix = "", out = {}) {
  if (value === undefined || value === null || value === "") return out;
  if (Array.isArray(value)) value.forEach((v, i) => flatten(v, prefix ? `${prefix}.${i + 1}` : String(i + 1), out));
  else if (typeof value === "object") Object.entries(value).forEach(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k, out));
  else out[prefix] = value;
  return out;
}
const Q = (action, params = {}) => ({
  svc: "ec2",
  headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8" },
  body: new URLSearchParams(flatten({ Action: action, ...params })).toString(),
});
const xid = (xml, tag) => { const m = String(xml).match(new RegExp(`<${tag}>(.*?)</${tag}>`)); return m ? m[1] : null; };
// ELBv2 is a separate AWS service ("elasticloadbalancing") sharing the same /_wire endpoint.
const ELB = (action, params = {}) => ({
  svc: "elasticloadbalancing",
  headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8" },
  body: new URLSearchParams(flatten({ Action: action, ...params })).toString(),
});

async function launchInstance(wire) {
  const body = await wire("POST", "/", Q("RunInstances", { InstanceType: "t3.micro", MinCount: 1, MaxCount: 1 }));
  return xid(body, "instanceId");
}

export default {
  "live-instance": async (wire) => launchInstance(wire),
  "live-ami": async (wire) => {
    const iid = await launchInstance(wire);
    const body = await wire("POST", "/", Q("CreateImage", { InstanceId: iid, Name: "v4-live-ami" }));
    return xid(body, "imageId");
  },
  "live-volume": async (wire) => {
    const body = await wire("POST", "/", Q("CreateVolume", { Size: 10, AvailabilityZone: "us-east-1a" }));
    return xid(body, "volumeId");
  },
  "live-snapshot": async (wire) => {
    const volBody = await wire("POST", "/", Q("CreateVolume", { Size: 10, AvailabilityZone: "us-east-1a" }));
    const volumeId = xid(volBody, "volumeId");
    const body = await wire("POST", "/", Q("CreateSnapshot", { VolumeId: volumeId, Description: "v4 live snapshot" }));
    return xid(body, "snapshotId");
  },
  "live-sg": async (wire, uniq) => {
    const body = await wire("POST", "/", Q("CreateSecurityGroup", { GroupName: uniq, GroupDescription: "v4 live security group" }));
    return xid(body, "groupId");
  },
  "live-eip": async (wire) => {
    const body = await wire("POST", "/", Q("AllocateAddress"));
    return xid(body, "allocationId");
  },
  "live-keypair": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateKeyPair", { KeyName: uniq }));
    return uniq;
  },
  "live-eni": async (wire) => {
    const subBody = await wire("POST", "/", Q("DescribeSubnets"));
    const subnetId = xid(subBody, "subnetId");
    const body = await wire("POST", "/", Q("CreateNetworkInterface", { SubnetId: subnetId, Description: "v4 live eni" }));
    return xid(body, "networkInterfaceId");
  },
  "live-placement-group": async (wire, uniq) => {
    await wire("POST", "/", Q("CreatePlacementGroup", { GroupName: uniq, Strategy: "cluster" }));
    return uniq;
  },
  "live-launch-template": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateLaunchTemplate", { LaunchTemplateName: uniq, "LaunchTemplateData.InstanceType": "t3.micro" }));
    return uniq;
  },
  "live-lb": async (wire, uniq) => {
    const subBody = await wire("POST", "/", Q("DescribeSubnets"));
    const ids = [...String(subBody).matchAll(/<subnetId>(.*?)<\/subnetId>/g)].map((m) => m[1]).slice(0, 2);
    await wire("POST", "/", ELB("CreateLoadBalancer", { Name: uniq, "Subnets.1": ids[0], "Subnets.2": ids[1] }));
    return uniq;
  },
  "live-tg": async (wire, uniq) => {
    const subBody = await wire("POST", "/", Q("DescribeSubnets"));
    const vpcId = xid(subBody, "vpcId") || "vpc-default";
    await wire("POST", "/", ELB("CreateTargetGroup", { Name: uniq, Protocol: "HTTP", Port: 80, VpcId: vpcId }));
    return uniq;
  },
};
