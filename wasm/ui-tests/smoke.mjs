import { startServer, bootConsole, chromium, describe, relayHealth } from "./lib.mjs";

const PATH = process.env.UI_PATH || "/aws-console.html";
const { server, base } = await startServer();
console.log("serving nano at", base, "— booting", PATH);
console.log("relay:", JSON.stringify(await relayHealth()));

const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();

try {
  const t0 = Date.now();
  const { errors } = await bootConsole(page, base, PATH);
  console.log(`booted in ${((Date.now() - t0) / 1000).toFixed(1)}s; pageerrors: ${errors.length}`);
  if (errors.length) console.log("  errors:", errors.slice(0, 5));

  // Enumerate the service rail
  const services = await page.evaluate(() => {
    const rail = document.querySelector("#rail");
    if (!rail) return [];
    return [...rail.querySelectorAll("a,button,li,[data-service],.svc,.service")]
      .map((e) => ({ text: (e.innerText || e.title || "").trim().split("\n")[0], ds: e.getAttribute("data-service") || "" }))
      .filter((x) => x.text).slice(0, 60);
  });
  console.log(`\nSERVICE RAIL (${services.length}):`);
  services.forEach((s) => console.log(`  - ${s.text}${s.ds ? "  [" + s.ds + "]" : ""}`));

  console.log("\n#main (initial):", JSON.stringify(await describe(page, "#main"), null, 1));

  // Try to open S3 and see what renders
  const clicked = await page.evaluate(() => {
    const rail = document.querySelector("#rail");
    const hit = [...rail.querySelectorAll("a,button,li,[data-service],.svc,.service")]
      .find((e) => /s3|storage|bucket/i.test((e.innerText || e.title || "") + (e.getAttribute("data-service") || "")));
    if (hit) { hit.click(); return (hit.innerText || "").trim().split("\n")[0]; }
    return null;
  });
  console.log("\nclicked service:", clicked);
  await new Promise((r) => setTimeout(r, 3000));
  console.log("#main (after S3 click):", JSON.stringify(await describe(page, "#main"), null, 1));
} catch (e) {
  console.log("SMOKE FAILED:", String(e).split("\n")[0]);
} finally {
  await browser.close();
  server.close();
}
