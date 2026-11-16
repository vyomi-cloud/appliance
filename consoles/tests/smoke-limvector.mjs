/* Round 8 search limits, driven in the Nano console against the real wire: GCP RAG Engine (live corpus counts after upload, import from the
 * simulated Cloud Storage, hybrid retrieval) and Vertex AI Search (GCS import + generated summary), and the Azure AI Search Data sources /
 * Indexers / Skillsets panels (Cosmos DB + Azure SQL indexers, status, semantic explorer query).
 *   node consoles/nano_preview.mjs --port 8793 --tier pro &   BASE=http://127.0.0.1:8793 SHOTS=/tmp/limvector node consoles/tests/smoke-limvector.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8793", SHOTS = process.env.SHOTS || "/tmp/limvector";
mkdirSync(SHOTS, { recursive: true });
const WIRE = `${BASE}/nano/_wire`;
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
const boot = async (path) => { await page.goto(`${BASE}/nano/v4/${path}/`); await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 }); await page.waitForTimeout(1200); };
const J = (method, path, body, headers) => page.evaluate(async ([u, m, b, h]) => { const r = await fetch(u, { method: m, headers: { "content-type": "application/json", ...(h || {}) }, body: b ? JSON.stringify(b) : undefined }); const t = await r.text(); try { return { status: r.status, ...JSON.parse(t) }; } catch { return { status: r.status, raw: t }; } }, [WIRE + path, method, body, headers]);
const RAW = (method, path, text, ct) => page.evaluate(async ([u, m, b, c]) => { const r = await fetch(u, { method: m, headers: { "content-type": c }, body: b }); return r.status; }, [WIRE + path, method, text, ct]);
const dlg = () => page.getByRole("dialog");
const body = () => page.locator("body").innerText();
const fillJson = async (name, nameLabel, obj) => { await dlg().getByLabel(nameLabel).fill(name); await dlg().getByLabel("JSON definition").fill(JSON.stringify(obj)); await dlg().getByRole("button", { name: "Create", exact: true }).click(); };

// ───────────────────────── GCP ─────────────────────────
await boot("gcp");
await page.evaluate(() => window.vyomiRegisterLLM({ model: "fake-webllm", chat: async () => JSON.stringify({ text: "The boiler is inspected every October [1].", input_tokens: 3, output_tokens: 9, finish_reason: "stop" }) }));
const project = await page.evaluate(() => localStorage.getItem("vyomi.v4.gcp.project") || "nano-project");
const go = async (hash, heading) => { await page.evaluate((h) => { location.hash = h; }, hash); await page.getByRole("heading", { name: heading, level: 1 }).first().waitFor({ timeout: 60000 }); await page.waitForTimeout(500); };
// a bucket with two documents in the simulated Cloud Storage
await J("POST", `/storage/v1/b?project=${project}`, { name: "kb-smoke" });
for (const [n, t] of [["docs/hvac.txt", "Boiler inspection happens every October. The chiller plant is serviced quarterly."], ["docs/lifts.txt", "The elevator maintenance contract renews in March."]])
  await RAW("POST", `/upload/storage/v1/b/kb-smoke/o?uploadType=media&name=${encodeURIComponent(n)}`, t, "text/plain");

await go("#/vertex-ai/rag-engine", "RAG Engine");
await page.getByRole("button", { name: "Create RAG corpus" }).first().click();
await dlg().getByLabel("Corpus name").fill("lim-corpus");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("lim-corpus").first().waitFor({ timeout: 20000 });
await page.getByText("Manage files").first().click();
await page.getByRole("button", { name: "Upload text file" }).click();
await dlg().getByLabel("Content").fill("The furnace room houses the boiler. Boiler inspection happens every October.");
await dlg().getByRole("button", { name: "Upload", exact: true }).click();
await page.getByText("notes.txt").first().waitFor({ timeout: 20000 });
await page.waitForTimeout(1500);
let corpora = (await J("GET", `/v1/projects/${project}/locations/us-central1/ragCorpora`)).ragCorpora || [];
let c = corpora.find((x) => x.displayName === "lim-corpus");
let rowText = await page.locator("tr", { hasText: "lim-corpus" }).first().innerText();
const m1 = rowText.match(/\b1\s+(\d+)\b/);
check("RAG: corpus list counts update right after an upload (no manual refresh)", !!c && c.vyomiStats.chunks >= 1 && !!m1 && Number(m1[1]) === c.vyomiStats.chunks, rowText.replace(/\s+/g, " "));
await page.getByRole("button", { name: "Import from Cloud Storage" }).click();
await dlg().getByLabel("Cloud Storage URIs").fill("gs://kb-smoke/docs/");
await dlg().getByRole("button", { name: "Import", exact: true }).click();
await page.getByText("hvac.txt").first().waitFor({ timeout: 30000 });
await page.waitForTimeout(1500);
corpora = (await J("GET", `/v1/projects/${project}/locations/us-central1/ragCorpora`)).ragCorpora || [];
c = corpora.find((x) => x.displayName === "lim-corpus");
rowText = await page.locator("tr", { hasText: "lim-corpus" }).first().innerText();
const m3 = rowText.match(/\b3\s+(\d+)\b/);
check("RAG: GCS import adds the objects (source column shows gs://) and the list shows 3 files with live chunk counts", c.vyomiStats.files === 3 && !!m3 && Number(m3[1]) === c.vyomiStats.chunks && /gs:\/\/kb-smoke\/docs\/hvac\.txt/.test(await body()), rowText.replace(/\s+/g, " "));
await page.getByLabel("Search mode").click(); await page.getByRole("option", { name: /Hybrid/ }).click();
await page.getByLabel("Test retrieval").fill("when is boiler inspection");
await page.getByRole("button", { name: "Retrieve" }).click();
await page.getByText(/distance .* score/).first().waitFor({ timeout: 30000 });
check("RAG: hybrid retrieval returns a cited context with distance and score", /Boiler inspection happens/.test(await body()));
await shot("gcp-rag");

await go("#/vertex-ai/search", "Search");
await page.getByRole("button", { name: "Create data store" }).click();
await dlg().getByLabel("Data store ID").fill("lim-docs");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("lim-docs").first().waitFor({ timeout: 20000 });
await page.getByRole("link", { name: "lim-docs" }).first().click();
await page.getByRole("button", { name: "Import from Cloud Storage" }).click();
await dlg().getByLabel("Cloud Storage URIs").fill("gs://kb-smoke/docs/");
await dlg().getByRole("button", { name: "Import", exact: true }).click();
await page.getByText(/docs-hvac-txt/).first().waitFor({ timeout: 30000 });
const ds = await J("GET", `/v1/projects/${project}/locations/global/collections/default_collection/dataStores/lim-docs`);
check("Search: GCS import creates 2 documents (live count on the wire)", ds.vyomiStats?.documents === 2, JSON.stringify(ds.vyomiStats));
await page.getByRole("checkbox", { name: "Generate summary" }).check();
await page.getByRole("textbox", { name: "Search", exact: true }).fill("when is the boiler inspected");
await page.getByRole("button", { name: "Search", exact: true }).last().click();
await page.getByTestId("search-summary").waitFor({ timeout: 60000 });
check("Search: generated summary from the local model is shown and labelled", /boiler is inspected every October/.test(await page.getByTestId("search-summary").innerText()) && /not Gemini/.test(await page.getByTestId("search-summary").innerText()));
await shot("gcp-search-summary");

// ───────────────────────── Azure ─────────────────────────
await boot("azure");
const S = "00000000-0000-0000-0000-cloudlearn01", RG = "lim-rg";
const A = `/subscriptions/${S}/resourceGroups/${RG}`;
const arm = (m, p, b, v = "2023-11-01") => J(m, `${p}${p.includes("?") ? "&" : "?"}api-version=${v}`, b);
await arm("PUT", `/subscriptions/${S}/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `${A}/providers/Microsoft.DocumentDB/databaseAccounts/limcosmos`, { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard" } }, "2024-05-15");
const CH = { "x-vyomi-account": "limcosmos" };
await J("POST", "/dbs", { id: "hotels" }, CH); await J("POST", "/dbs/hotels/colls", { id: "rooms", partitionKey: { paths: ["/city"], kind: "Hash" } }, CH);
for (const [i, nm, city] of [[1, "Lakeview", "Oslo"], [2, "Harbor", "Bergen"]]) await J("POST", "/dbs/hotels/colls/rooms/docs", { id: `h${i}`, name: nm, city, rating: 3 + i }, { ...CH, "x-ms-documentdb-partitionkey": JSON.stringify([city]) });
await J("PUT", "/azure-sql/servers/limsql"); await J("PUT", "/azure-sql/servers/limsql/databases/shop");
const Q = (sql) => J("POST", "/azure-sql/servers/limsql/databases/shop/query", { sql });
await Q("CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, descr TEXT)"); await Q("INSERT INTO products VALUES ('p1','Desk lamp','LED lamp for the desk'),('p2','Office chair','Ergonomic chair with lumbar support')");
const SB = `${A}/providers/Microsoft.Search/searchServices/limsearch`;
check("seed search service", (await arm("PUT", SB, { location: "eastus", sku: { name: "standard" } })).status < 300);
const sem = { defaultConfiguration: "sc", configurations: [{ name: "sc", prioritizedFields: { titleField: { fieldName: "name" }, prioritizedContentFields: [{ fieldName: "descr" }] } }] };
await arm("PUT", `${SB}/indexes/hotels`, { fields: [{ name: "id", type: "Edm.String", key: true }, { name: "name", type: "Edm.String", searchable: true }, { name: "city", type: "Edm.String", searchable: true, filterable: true }, { name: "descr", type: "Edm.String", searchable: true }], semantic: sem });
await arm("PUT", `${SB}/indexes/products`, { fields: [{ name: "sku", type: "Edm.String", key: true }, { name: "title", type: "Edm.String", searchable: true }, { name: "descr", type: "Edm.String", searchable: true }], semantic: { defaultConfiguration: "sc", configurations: [{ name: "sc", prioritizedFields: { titleField: { fieldName: "title" }, prioritizedContentFields: [{ fieldName: "descr" }] } }] } });
const goA = async (panel) => { await page.evaluate((h) => { location.hash = h; }, `#/aisearch/${RG}/limsearch/${panel}`); await page.waitForTimeout(900); };

await goA("datasources");
await page.getByRole("button", { name: "Add Cosmos DB source" }).click();
await fillJson("cosmos-ds", "Data source name", { type: "cosmosdb", credentials: { connectionString: "AccountEndpoint=https://limcosmos.documents.azure.com:443/;AccountKey=a2V5;Database=hotels;" }, container: { name: "rooms" }, dataChangeDetectionPolicy: { "@odata.type": "#Microsoft.Azure.Search.HighWaterMarkChangeDetectionPolicy", highWaterMarkColumnName: "_ts" } });
await page.getByRole("cell", { name: "cosmos-ds", exact: true }).waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "Add SQL source" }).click();
await fillJson("sql-ds", "Data source name", { type: "azuresql", credentials: { connectionString: "Server=tcp:limsql.database.windows.net,1433;Database=shop;User ID=u;Password=p;" }, container: { name: "dbo.products" } });
await page.getByRole("cell", { name: "sql-ds", exact: true }).waitFor({ timeout: 20000 });
check("Data sources: Cosmos DB and SQL sources listed with their types", /cosmosdb/.test(await body()) && /azuresql/.test(await body()) && !/their indexers report the failure/.test(await body()));
await shot("azure-datasources");

await goA("skillsets");
await page.getByRole("button", { name: "Add skillset" }).click();
await fillJson("split-merge", "Skillset name", { skills: [{ "@odata.type": "#Microsoft.Skills.Text.SplitSkill", name: "s", textSplitMode: "sentences", context: "/document", inputs: [{ name: "text", source: "/document/descr" }], outputs: [{ name: "textItems", targetName: "sents" }] },
  { "@odata.type": "#Microsoft.Skills.Text.MergeSkill", name: "m", context: "/document", inputs: [{ name: "text", source: "/document/descr" }], outputs: [{ name: "mergedText", targetName: "merged" }] }] });
await page.getByRole("cell", { name: "split-merge", exact: true }).waitFor({ timeout: 20000 });
check("Skillsets: created and listed with skill types", /Text\.SplitSkill, Text\.MergeSkill/.test(await body()));

await goA("indexers");
await page.getByRole("button", { name: "Add indexer" }).click();
await fillJson("cosmos-ix", "Indexer name", { dataSourceName: "cosmos-ds", targetIndexName: "hotels", fieldMappings: [{ sourceFieldName: "id", targetFieldName: "id" }] });
await page.getByRole("cell", { name: "cosmos-ix", exact: true }).waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "Run cosmos-ix" }).click();
await page.getByTestId("indexer-status").waitFor({ timeout: 30000 });
const stxt = await page.getByTestId("indexer-status").innerText();
const hotels = await arm("POST", `${SB}/indexes/hotels/docs/search`, { search: "*", select: "id,name" });
check("Indexers: a Cosmos DB indexer runs from the console (2 items, success, tracking state)", /"status": "success"/.test(stxt) && /"itemsProcessed": 2/.test(stxt) && /finalTrackingState": "\d+/.test(stxt) && (hotels.value || []).length === 2, stxt.replace(/\s+/g, " "));
await page.getByRole("button", { name: "Add indexer" }).click();
await fillJson("sql-ix", "Indexer name", { dataSourceName: "sql-ds", targetIndexName: "products", fieldMappings: [{ sourceFieldName: "name", targetFieldName: "title" }] });
await page.getByRole("cell", { name: "sql-ix", exact: true }).waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "Run sql-ix" }).click();
await page.getByText(/Execution status: sql-ix/).waitFor({ timeout: 30000 });
const prods = await arm("POST", `${SB}/indexes/products/docs/search`, { search: "ergonomic", select: "sku,title" });
check("Indexers: an Azure SQL indexer maps name -> title and the rows are searchable", prods.value?.[0]?.sku === "p2" && prods.value[0].title === "Office chair", JSON.stringify(prods.value));
await page.getByRole("button", { name: "Add indexer" }).click();
await fillJson("bad-ix", "Indexer name", { dataSourceName: "cosmos-ds", targetIndexName: "products", fieldMappings: [{ sourceFieldName: "id", targetFieldName: "nope", mappingFunction: { name: "doesNotExist" } }] });
await page.waitForTimeout(1200);
check("Indexers: an unsupported mapping function is a visible request error", /Mapping function/.test(await body()));
await page.getByRole("button", { name: "Cancel" }).click();
await page.getByRole("button", { name: "Status cosmos-ix" }).click();
await page.getByText(/Execution status: cosmos-ix/).waitFor({ timeout: 20000 });
check("Indexers: Status button shows the stored last result without re-running", /itemsProcessed/.test(await page.getByTestId("indexer-status").innerText()));
await shot("azure-indexers");

await goA("indexes");
await page.getByRole("button", { name: "hotels", exact: true }).click();
await page.getByTestId("search-explorer").waitFor();
await page.getByLabel("Query string").fill("lakeview");
await page.getByLabel("Query type").selectOption("semantic");
await page.getByRole("button", { name: "Search", exact: true }).click();
await page.getByTestId("search-results").waitFor({ timeout: 30000 });
const rt = await page.getByTestId("search-results").innerText();
check("Explorer: semantic query type returns @search.rerankerScore", /@search\.rerankerScore/.test(rt) && /Lakeview/.test(rt), rt.slice(0, 160));
await shot("azure-semantic");
check("no page errors", errs.length === 0, errs.join(" | "));
await browser.close();
const bad = results.filter((x) => !x).length;
console.log(bad ? `\n${bad} FAILED` : `\nALL ${results.length} PASS`);
process.exit(bad ? 1 : 0);
