/* UI-conformance fixtures for VPC network — native Compute Engine REST API v1 (svc: null,
 * no AWS signature). Each returns the text the page must then show (liveness: proves the
 * page is not static). See consoles/src/aws/services/s3/fixtures.mjs for the pattern. */
const PROJECT = "vyomi-project";
const base = `/compute/v1/projects/${PROJECT}`;

async function ensureNetwork(wire, name = "uic-network") {
  await wire("POST", `${base}/global/networks`, { svc: null, body: { name, autoCreateSubnetworks: false } }).catch(() => {});
  return name;
}

const ctBase = `/v1/projects/${PROJECT}/locations/global/connectivityTests`;

async function ensureConnectivityTest(wire, tid = "uic-ct") {
  await wire("POST", `${ctBase}?testId=${tid}`, {
    svc: null, body: { source: { ipAddress: "203.0.113.9" }, destination: { ipAddress: "203.0.113.10", port: 443 }, protocol: "TCP" },
  }).catch(() => {});
  return tid;
}

export default {
  "gcp-network": async (wire) => ensureNetwork(wire),

  "live-network": async (wire, uniq) => {
    await wire("POST", `${base}/global/networks`, { svc: null, body: { name: uniq, autoCreateSubnetworks: false } });
    return uniq;
  },

  "live-subnet": async (wire, uniq) => {
    await ensureNetwork(wire);
    await wire("POST", `${base}/regions/us-central1/subnetworks`, {
      svc: null, body: { name: uniq, network: "uic-network", ipCidrRange: "10.50.0.0/24" },
    });
    return uniq;
  },

  "live-firewall": async (wire, uniq) => {
    await ensureNetwork(wire);
    await wire("POST", `${base}/global/firewalls`, {
      svc: null, body: { name: uniq, network: "uic-network", direction: "INGRESS", allowed: [{ IPProtocol: "tcp", ports: ["22"] }] },
    });
    return uniq;
  },

  "live-route": async (wire, uniq) => {
    await ensureNetwork(wire);
    await wire("POST", `${base}/global/routes`, {
      svc: null, body: { name: uniq, network: "uic-network", destRange: "0.0.0.0/0", nextHopGateway: "default-internet-gateway" },
    });
    return uniq;
  },

  "live-address": async (wire, uniq) => {
    await wire("POST", `${base}/regions/us-central1/addresses`, { svc: null, body: { name: uniq, addressType: "INTERNAL" } });
    return uniq;
  },

  "gcp-connectivity-test": async (wire) => ensureConnectivityTest(wire),

  "live-connectivity-test": async (wire, uniq) => {
    await wire("POST", `${ctBase}?testId=${uniq}`, {
      svc: null, body: { source: { ipAddress: "203.0.113.9" }, destination: { ipAddress: "203.0.113.10", port: 443 }, protocol: "TCP" },
    });
    return uniq;
  },

  "live-connectivity-test-detail": async (wire, uniq) => {
    await ensureConnectivityTest(wire);
    await wire("PATCH", `${ctBase}/uic-ct`, { svc: null, body: { description: uniq } });
    return uniq;
  },
};
