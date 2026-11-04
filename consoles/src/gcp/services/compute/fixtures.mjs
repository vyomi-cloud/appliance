/* UI-conformance fixtures for Compute Engine (native Compute Engine REST v1, no SigV4).
 * See s3/fixtures.mjs and kms/fixtures.mjs for the pattern. */
const PROJECT = "vyomi-project";
const ZONE = "us-central1-a";
const B = (path) => `/compute/v1/projects/${PROJECT}${path}`;
const gce = (wire, method, path, body) => wire(method, B(path), { svc: null, body: body ?? {} });

const bootDisk = () => ({ boot: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12", diskSizeGb: 10 } });

export default {
  "live-instance": async (wire, uniq) => {
    await gce(wire, "POST", `/zones/${ZONE}/instances`, { name: uniq, machineType: "e2-medium", disks: [bootDisk()] });
    return uniq;
  },
  "live-disk": async (wire, uniq) => {
    await gce(wire, "POST", `/zones/${ZONE}/disks`, { name: uniq, sizeGb: 10, type: "pd-balanced" });
    return uniq;
  },
  "live-snapshot": async (wire, uniq) => {
    const disk = `${uniq}-src`;
    await gce(wire, "POST", `/zones/${ZONE}/disks`, { name: disk, sizeGb: 10 });
    await gce(wire, "POST", `/zones/${ZONE}/disks/${disk}:createSnapshot`, { name: uniq });
    return uniq;
  },
  "live-image": async (wire, uniq) => {
    const disk = `${uniq}-src`;
    await gce(wire, "POST", `/zones/${ZONE}/disks`, { name: disk, sizeGb: 10 });
    await gce(wire, "POST", "/global/images", { name: uniq, sourceDisk: disk });
    return uniq;
  },
  "live-machine-image": async (wire, uniq) => {
    const inst = `${uniq}-src`;
    await gce(wire, "POST", `/zones/${ZONE}/instances`, { name: inst, machineType: "e2-medium", disks: [bootDisk()] });
    await gce(wire, "POST", "/global/machineImages", { name: uniq, sourceInstance: inst });
    return uniq;
  },
  "live-instance-template": async (wire, uniq) => {
    await gce(wire, "POST", "/global/instanceTemplates", { name: uniq, properties: { machineType: "e2-medium" } });
    return uniq;
  },
  "live-instance-group": async (wire, uniq) => {
    await gce(wire, "POST", `/zones/${ZONE}/instanceGroups`, { name: uniq });
    return uniq;
  },
  "live-health-check": async (wire, uniq) => {
    await gce(wire, "POST", "/global/healthChecks", { name: uniq, type: "HTTP", httpHealthCheck: { port: 80, requestPath: "/" } });
    return uniq;
  },
  // Zones page: a freshly created instance in a zone makes that zone's row show the
  // instance's name (the Zones table's extra "Instances in use" cell reflects real state).
  "live-zone-instance": async (wire, uniq) => {
    await gce(wire, "POST", `/zones/${ZONE}/instances`, { name: uniq, machineType: "e2-medium", disks: [bootDisk()] });
    return uniq;
  },
  // Operations page: any mutation produces an Operation whose Target column shows the
  // mutated resource's own name.
  "live-operation": async (wire, uniq) => {
    await gce(wire, "POST", "/global/healthChecks", { name: uniq, type: "TCP" });
    return uniq;
  },
};
