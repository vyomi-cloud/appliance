/* GCP console: every grid has a Columns button that shows/hides columns (first column stays), remembered per grid.
 * Covers a service list grid (VPC networks) and a sub-tab grid (VPC > Subnets). Nano: default (NANO_DIR=<wasm dir>). */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const b = await chromium.launch(); const p = await (await b.newContext({viewport:{width:1400,height:800}})).newPage();
const errs=[]; p.on("pageerror",e=>errs.push(String(e)));
const res=[]; const check=(n,ok,note="")=>{res.push(ok);console.log(`[${ok?"PASS":"FAIL"}] ${n}${ok?"":" "+note}`)};
await bootConsole(p, base, "/gcp-console.html");
await p.waitForFunction(() => typeof PROJECT === "string" && PROJECT && typeof api === "function", null, {timeout:120000});
await p.evaluate(async()=>{ await fetch(`/api/gcp/compute/v1/projects/${PROJECT}/global/networks`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({name:"my-vpc"})}); });
const visible = label => p.evaluate(l => { const th=[...document.querySelectorAll("#main table.gc th[data-label]")].find(x=>x.getAttribute("data-label")===l); return !!th && getComputedStyle(th).display!=="none"; }, label);
const cellVisible = label => p.evaluate(l => { const td=document.querySelector(`#main table.gc td[data-label="${l}"]`); return !!td && getComputedStyle(td).display!=="none"; }, label);
async function chooser(name, hideLabel){
  const btn=p.locator("#main .vy-colmenu > button").first();
  check(name+": has a Columns button", (await btn.count())===1);
  await btn.click(); const pop=p.locator("#main .vy-colpop").first();
  check(name+": the menu lists the columns", (await pop.locator(".vy-colrow").count())>=3);
  check(name+": first column can't be hidden", await pop.locator(".vy-colrow input").first().isDisabled());
  check(name+": '"+hideLabel+"' is visible before", await visible(hideLabel));
  await pop.locator(".vy-colrow").filter({has:p.getByText(hideLabel,{exact:true})}).locator("input").uncheck();
  check(name+": unchecking hides the header and cells", !(await visible(hideLabel)) && !(await cellVisible(hideLabel)));
  await p.mouse.click(1380,640); await sleep(200);
  check(name+": clicking outside closes the menu", await pop.isHidden());
}
// list grid
await p.evaluate(()=>navigate({view:"list",service:"vpc",item:null})); await sleep(2500);
const listLabels = await p.evaluate(()=>[...document.querySelectorAll("#main table.gc th[data-label]")].map(t=>t.getAttribute("data-label")));
await chooser("list grid", listLabels[1]);
await p.evaluate(()=>navigate({view:"list",service:"vpc",item:null})); await sleep(2000);
check("list grid: the choice is remembered after re-opening", !(await visible(listLabels[1])));
await p.locator("#main .vy-colmenu > button").first().click();
await p.locator("#main .vy-colpop .vy-colfoot a").click(); await sleep(200);
check("list grid: Show all restores the column", await visible(listLabels[1]));
// sub-tab grid
await p.locator("#main a").filter({hasText:"my-vpc"}).first().click(); await sleep(2000);
await p.locator(".sub-nav a.nav-item",{hasText:"Subnets"}).first().click(); await sleep(1500);
await chooser("subnets grid", "Gateway");
await p.locator(".sub-nav a.nav-item",{hasText:"Routes"}).first().click(); await sleep(1200);
await p.locator(".sub-nav a.nav-item",{hasText:"Subnets"}).first().click(); await sleep(1500);
check("subnets grid: the choice is remembered after switching tabs", !(await visible("Gateway")));
await p.screenshot({path:"/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/56440f95-4078-4730-9852-08a9021227ad/scratchpad/gcp-cols.png"});
check("no page errors", errs.length===0, errs.join(";").slice(0,200));
await b.close(); server.close(); process.exit(res.every(Boolean)?0:1);
