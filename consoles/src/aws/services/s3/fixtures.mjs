/* UI-conformance fixtures for S3 — native-wire setup run by consoles/tests/ui-conformance.mjs.
 * Each returns the text the page must then show (liveness: proves the page is not static). */
export default {
  "s3-bucket": async (wire) => { await wire("PUT", "/uic-bucket").catch(() => {}); await wire("PUT", "/uic-bucket/uic-object.txt", { body: "x" }); return "uic-bucket"; },
  "live-bucket": async (wire, uniq) => { await wire("PUT", `/${uniq}`); return uniq; },
  "live-object": async (wire, uniq) => { await wire("PUT", "/uic-bucket").catch(() => {}); await wire("PUT", `/uic-bucket/${uniq}.txt`, { body: "live" }); return `${uniq}.txt`; },
};
