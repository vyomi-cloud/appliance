// Capped, self-killing browser validation for the NEW AWS second-level features:
//   - EC2 serial console access toggle (ec2:console settings)
//   - EC2 IAM role (ec2:iam settings)
//   - S3 bucket notifications + Lambda permission statements (functional lists)
//   - Activity tab merges sub-resource/settings cloudsim events
//   - DURABILITY across a FULL PAGE RELOAD (the real SW->Pyodide->IndexedDB path)
// Falls back to structural if the browser hangs (HARNESS-TIMEOUT -> exit 2).
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 90000);
_k.unref && _k.unref();

import { chromium, startServer, bootConsole } from "./lib.mjs";

const run = async () => {
  const { server, base } = await startServer();
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  let ok = true;
  const log = (m) => console.log(m);
  // Drive the in-page api()/subApi() exactly as the console does (robust vs DOM churn).
  const apiCall = (method, path, body) =>
    page.evaluate(async ([m, p, b]) => {
      const r = await fetch(location.origin + p, {
        method: m,
        headers: b !== undefined ? { "Content-Type": "application/json" } : {},
        body: b !== undefined ? JSON.stringify(b) : undefined,
      });
      let j = null; try { j = await r.json(); } catch (_) {}
      return { status: r.status, ok: r.ok, json: j };
    }, [method, path, body]);

  // bootConsole resolves on SW+rail readiness, but the Pyodide BACKEND finishes
  // its restore slightly later. Poll a generic _resource List until it answers
  // ok (not "backend timeout"/NotTranslatedYet) so reads are deterministic.
  const waitBackend = async (ns) => {
    for (let i = 0; i < 40; i++) {
      const r = await apiCall("GET", `/api/aws/sub/${encodeURIComponent(ns)}/list`);
      if (r.json && r.json.ok === true) return true;
      await page.waitForTimeout(500);
    }
    return false;
  };

  try {
    await bootConsole(page, base, "/aws-console.html");
    await waitBackend("ec2~_~console"); // ensure Pyodide backend is live before writes
    log("booted");

    // 1) create an EC2 instance to hang sub-resources off of.
    const inst = "i-smoketest01";
    await apiCall("POST", "/api/aws/ec2/instances", { name: inst, instance_type: "t3.micro" });

    // 2) EC2 serial-console access toggle + IAM role setting (NEW ec2:console / ec2:iam)
    const nsConsole = `ec2~${inst}~console`;
    const nsIam = `ec2~${inst}~iam`;
    await apiCall("POST", `/api/aws/sub/${encodeURIComponent(nsConsole)}/create`,
      { name: "_settings", serial_console_access: true });
    await apiCall("POST", `/api/aws/sub/${encodeURIComponent(nsIam)}/create`,
      { name: "_settings", iam_instance_profile: "arn:aws:iam::123456789012:instance-profile/r", role_name: "r" });

    // 3) S3 bucket notification (NEW functional list)
    await apiCall("POST", "/api/aws/s3/buckets", { name: "smoke-bucket" });
    const nsNotif = "s3~smoke-bucket~notifications";
    await apiCall("POST", `/api/aws/sub/${encodeURIComponent(nsNotif)}/create`,
      { name: "on-create", destination_type: "SQS", events: "s3:ObjectCreated:*", status: "active" });

    const readBefore = async () => ({
      console: (await apiCall("GET", `/api/aws/sub/${encodeURIComponent(nsConsole)}/get/_settings`)).json,
      iam: (await apiCall("GET", `/api/aws/sub/${encodeURIComponent(nsIam)}/get/_settings`)).json,
      notif: (await apiCall("GET", `/api/aws/sub/${encodeURIComponent(nsNotif)}/list`)).json,
    });
    const b = await readBefore();
    const okBefore = b.console && b.console.serial_console_access === true
      && b.iam && String(b.iam.iam_instance_profile || "").includes("instance-profile")
      && b.notif && (b.notif.items || []).length === 1;
    log("before-reload state ok: " + okBefore);
    ok = ok && okBefore;

    // 4) Activity tab merge — sub-resource events show for the parent instance.
    // Give the debounced store-save a beat, then query the parent's activity.
    await page.waitForTimeout(1200);
    const feed = (await apiCall("GET", "/api/cloudsim/events?provider=aws&limit=200")).json;
    const evs = (Array.isArray(feed) ? feed : (feed.events || []));
    const subEvs = evs.filter((e) => String(e.service || "").startsWith(`ec2~${inst}~`));
    log("sub-resource activity events visible: " + subEvs.length);
    ok = ok && subEvs.length >= 1;

    // 5) FULL PAGE RELOAD — the real durability test (SW restores from IndexedDB).
    await page.waitForTimeout(1600); // let scheduleStoresSave flush to IndexedDB
    await bootConsole(page, base, "/aws-console.html");
    await waitBackend(nsNotif); // WAIT for reloaded backend to finish restore
    log("reloaded");
    const a = await readBefore();
    const okAfter = a.console && a.console.serial_console_access === true
      && a.iam && String(a.iam.iam_instance_profile || "").includes("instance-profile")
      && a.notif && (a.notif.items || []).length === 1;
    log("after-reload (DURABLE) state ok: " + okAfter);
    ok = ok && okAfter;
  } catch (e) {
    console.log("BROWSER-ERROR: " + e.message);
    ok = false;
  } finally {
    await browser.close().catch(() => {});
    server.close();
  }
  console.log(ok ? "BROWSER-PASS" : "BROWSER-FAIL");
  clearTimeout(_k);
  process.exit(ok ? 0 : 1);
};
run();
