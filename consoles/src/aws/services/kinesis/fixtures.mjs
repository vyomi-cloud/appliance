/* UI-conformance fixtures for Kinesis (native Kinesis_20131202 JSON). See s3/fixtures.mjs. */
const T = (op) => ({ svc: "kinesis", target: `Kinesis_20131202.${op}` });

export default {
  "live-stream": async (wire, uniq) => {
    await wire("POST", "/", { ...T("CreateStream"), body: { StreamName: uniq, ShardCount: 1, StreamModeDetails: { StreamMode: "PROVISIONED" } } });
    return uniq;
  },
};
