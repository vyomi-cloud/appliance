/* GCP console VPC tabs: Private Google Access and Flow logs are switches (no Actions button); Routes has a leading
 * checkbox column and a Delete button on top that deletes the selected rows (system subnet routes are not selectable).
 * Nano: default (NANO_DIR=<wasm dir>). */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const S="/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/56440f95-4078-4730-9852-08a9021227ad/scratchpad/";
const { server, base } = await startServer();
const b = await chromium.launch(); const p = await (await b.newContext({viewport:{width:1400,height:800}})).newPage();
const errs=[]; p.on("pageerror",e=>errs.push(String(e)));
const res=[]; const check=(n,ok,note="")=>{res.push(ok);console.log(`[${ok?"PASS":"FAIL"}] ${n}${ok?"":" "+note}`)};
await bootConsole(p, base, "/gcp-console.html");
await p.waitForFunction(() => typeof PROJECT === "string" && PROJECT && typeof api === "function", null, {timeout:120000});
await p.evaluate(async()=>{ const h={method:"POST",headers:{"content-type":"application/json"}}; const B=`/api/gcp/compute/v1/projects/${PROJECT}/global/networks`;
  await fetch(B,{...h,body:JSON.stringify({name:"my-vpc"})}); });
await p.evaluate(()=>navigate({view:"list",service:"vpc",item:null})); await sleep(2000);
await p.locator("#main a").filter({hasText:"my-vpc"}).first().click(); await sleep(2000);
const tab=async t=>{ await p.locator(".sub-nav a.nav-item",{hasText:t}).first().click(); await sleep(1500); };
// Subnets
await tab("Subnets");
const sw = p.locator("#main .vy-sw input"); const n0=await sw.count();
check("subnets: Private Google Access is a switch (not a button)", n0>0 && !(await p.locator("#main button",{hasText:"Toggle Private"}).count()), "switches="+n0);
check("subnets: no Toggle button", (await p.locator("#main button",{hasText:/Toggle/}).count())===0);
if (n0) { const before=await sw.first().isChecked(); await sw.first().locator("xpath=..").click(); await sleep(1500);
  const after=await p.locator("#main .vy-sw input").first().isChecked(); check("subnets: flipping the switch changes the state", before!==after, `${before}->${after}`); }
await p.screenshot({path:S+"gcp-subnets.png"});
// Routes
await tab("Routes");
await p.evaluate(async()=>{ const svc=svcByKey("vpc"); const nm=STATE.item.name; await subPost(svc,"createRoute",nm,{name:"r-del-1",destRange:"192.0.2.0/24",nextHopType:"gateway",priority:1000}); await subPost(svc,"createRoute",nm,{name:"r-del-2",destRange:"198.51.100.0/24",nextHopType:"gateway",priority:1000}); });
await tab("Routes"); await tab("Routes");
check("routes: no Actions column", (await p.locator("#main th",{hasText:"Actions"}).count())===0);
check("routes: checkbox is the first column", (await p.locator("#main table.gc tr").first().locator("th").first().locator("input[type=checkbox]").count())===1);
const del=p.locator("#main .sub-content button.btn.danger").first();
check("routes: Delete button on top, disabled until a row is selected", (await del.count())===1 && await del.isDisabled());
const rowOf=name=>p.locator("#main table.gc tr",{hasText:name});
const sysBox=p.locator("#main table.gc tr",{hasText:"Subnet route"}).first().locator("input[type=checkbox]");
if (await sysBox.count()) check("routes: system subnet routes can't be selected", await sysBox.isDisabled());
await rowOf("r-del-1").locator("input[type=checkbox]").check(); await rowOf("r-del-2").locator("input[type=checkbox]").check();
check("routes: selecting rows enables Delete (2)", !(await del.isDisabled()) && /\(2\)/.test(await del.innerText()), await del.innerText());
await p.screenshot({path:S+"gcp-routes.png"});
p.once("dialog", d=>d.accept()); await del.click(); await sleep(2000);
check("routes: Delete removes the selected rows", (await p.locator("#main table.gc tr",{hasText:/r-del-[12]/}).count())===0);
// Flow logs
await tab("Flow logs");
const fsw=p.locator("#main .vy-sw input"); const fn=await fsw.count();
check("flow logs: switch column, no Actions column", fn>0 && (await p.locator("#main th",{hasText:"Actions"}).count())===0, "switches="+fn);
if (fn) { const bf=await fsw.first().isChecked(); await fsw.first().locator("xpath=..").click(); await sleep(1500);
  check("flow logs: flipping the switch changes the state", bf!==(await p.locator("#main .vy-sw input").first().isChecked())); }
await p.screenshot({path:S+"gcp-flowlogs.png"});
check("no page errors", errs.length===0, errs.join(";").slice(0,200));
await b.close(); server.close(); process.exit(res.every(Boolean)?0:1);
