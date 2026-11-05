/* Host access to in-browser databases (vyomi-tunnel /db bridge + wasm/db-bridge.js + wire front ends). Needs: a Nano preview, a tunnel >=1.2.0 on :8191
 * (RELAY_PORT=8191 node wasm/relay/local-relay.mjs), host clients: psql, python with pymysql+psycopg, node mysql2 (dir in $PGL). Postgres is only
 * served where PGlite is the RDS engine; the v4 page path uses sqlite, so there that endpoint is (correctly) absent. */
const pw = require(process.env.PW); const cp = require("child_process");
const BASE = process.env.BASE, TUN = "http://127.0.0.1:8191", UI = BASE + "/nano/v4/aws/", WIRE = BASE + "/nano/_wire";
const N = Date.now() % 100000, PGDB = "pgdb" + N, MYDB = "mydb" + N;
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const sh = (cmd, env) => { try { return cp.execSync(cmd, { env: { ...process.env, ...env }, encoding: "utf8", timeout: 60000, stdio: ["ignore", "pipe", "pipe"] }); } catch (e) { return "ERR " + (e.stdout || "") + (e.stderr || e.message); } };
let pass = 0, fail = 0; const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log((c ? "PASS " : "FAIL ") + n + (c ? "" : " :: " + String(d).slice(0, 300))); };
(async () => {
  const b = await pw.chromium.launch(); const ctx = await b.newContext();
  await ctx.addInitScript(() => { try { localStorage.setItem("nano_local_ext", "http://127.0.0.1:8191"); } catch (_) {} });
  const pg = await ctx.newPage(); pg.on("pageerror", (e) => console.log("pageerror", String(e.message).slice(0, 150)));
  await pg.goto(UI, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  const Q = (a) => pg.evaluate(async ([u, au, body]) => { const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-www-form-urlencoded" }, body }); return { s: r.status, t: await r.text() }; }, [WIRE, auth("rds"), new URLSearchParams({ Version: "2014-10-31", ...a }).toString()]);
  const mk = (id, engine) => Q({ Action: "CreateDBInstance", DBInstanceIdentifier: id, Engine: engine, DBInstanceClass: "db.t3.micro", MasterUsername: "master", MasterUserPassword: "pw12345678", AllocatedStorage: "25" });
  ok("create postgres instance", (await mk(PGDB, "postgres")).s === 200);
  ok("create mysql instance", (await mk(MYDB, "mysql")).s === 200);
  // wait for the bridge to register both with the tunnel
  let dbs = [];
  for (let i = 0; i < 40; i++) { dbs = (await (await fetch(TUN + "/health")).json()).dbs || []; if (dbs.length >= 2) break; await new Promise((r) => setTimeout(r, 1500)); }
  console.log("tunnel dbs:", JSON.stringify(dbs));
  const pgEp = dbs.find((d) => d.engine === "postgres"), myEp = dbs.find((d) => d.engine === "mysql");
  ok("tunnel lists a postgres endpoint", !!pgEp); ok("tunnel lists a mysql endpoint", !!myEp);
  if (pgEp) {
    const o = sh(`psql "host=127.0.0.1 port=${pgEp.host_port} user=master dbname=postgres sslmode=prefer" -v ON_ERROR_STOP=1 -At -c "CREATE TABLE hosts(id serial primary key, n text)" -c "INSERT INTO hosts(n) VALUES ('from-psql')" -c "SELECT id||':'||n FROM hosts"`, { PGPASSWORD: "pw12345678" });
    ok("psql on the host reaches the in-browser Postgres (port " + pgEp.host_port + ")", /1:from-psql/.test(o), o);
    const py = sh(`/Users/sudhirganti/Applications/simulator/appliance/.venv/bin/python -c "import psycopg;c=psycopg.connect('host=127.0.0.1 port=${pgEp.host_port} user=master dbname=postgres password=x sslmode=disable',autocommit=True);print(c.execute('SELECT n FROM hosts WHERE id=%s',(1,)).fetchone()[0])"`);
    ok("psycopg (parameters) reads the same data", /from-psql/.test(py), py);
  }
  if (myEp) {
    const o = sh(`/Users/sudhirganti/Applications/simulator/appliance/.venv/bin/python - <<'PY'
import pymysql
c = pymysql.connect(host="127.0.0.1", port=${myEp.host_port}, user="master", password="pw12345678", autocommit=True)
cur = c.cursor()
cur.execute("CREATE TABLE \`orders\` (\`id\` INT(11) NOT NULL AUTO_INCREMENT, \`sku\` VARCHAR(40) NOT NULL, \`note\` TEXT, PRIMARY KEY (\`id\`), KEY \`idx_sku\` (\`sku\`)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
cur.execute("INSERT INTO orders (sku, note) VALUES (%s, %s)", ("a-1", "it's quoted \\\\ ok"))
print("lastrowid", cur.lastrowid)
cur.execute("INSERT INTO orders (sku) VALUES ('b-2') ON DUPLICATE KEY UPDATE sku = VALUES(sku)")
cur.execute("SELECT id, CONCAT(sku, '#', id), note FROM orders ORDER BY id LIMIT 0, 5")
print("rows", cur.fetchall())
cur.execute("SHOW TABLES"); print("tables", cur.fetchall())
cur.execute("SELECT VERSION()"); print("version", cur.fetchone())
try: cur.execute("SELECT * FROM nope")
except pymysql.err.ProgrammingError as e: print("err", e.args[0])
PY`);
    console.log(o.trim());
    ok("pymysql on the host: MySQL DDL/DML/SHOW/functions via the translator", /lastrowid 1/.test(o) && /a-1#1/.test(o) && /'orders'/.test(o) && /err 1146/.test(o), o);
    const m2 = sh(`cd ${process.env.PGL} && node -e "
const mysql=require('mysql2/promise');(async()=>{const c=await mysql.createConnection({host:'127.0.0.1',port:${myEp.host_port},user:'master',password:'x'});
const [r]=await c.execute('SELECT sku FROM orders WHERE id >= ? ORDER BY id',[1]);console.log(JSON.stringify(r));
const [i]=await c.execute('INSERT INTO orders (sku) VALUES (?)',['mysql2-c']);console.log('insertId',i.insertId);await c.end();})().catch(e=>{console.log('E',e.message)})"`);
    ok("mysql2 prepared statements (binary protocol) work", /a-1/.test(m2) && /insertId 3/.test(m2), m2);
  }
  console.log(`${pass} passed, ${fail} failed`);
  await b.close();
})();
