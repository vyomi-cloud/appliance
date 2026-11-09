/* "Create a database" on the Create Web App wizard's Database tab. Everything here is REAL
 * native ARM / Cosmos wire against the existing Vyomi cores (no new backend):
 *   Azure SQL:  Microsoft.Sql/servers (new server only) -> servers/{s}/databases/{db}
 *   Cosmos DB:  Microsoft.DocumentDB/databaseAccounts (new account only) -> listConnectionStrings
 *               and, on the Cosmos data plane (/dbs, x-vyomi-account), the database + container
 * The result is written into the web app's connection strings (sites/config/connectionstrings),
 * the same place the real portal puts AZURE_SQL_CONNECTIONSTRING / AZURE_COSMOS_CONNECTIONSTRING. */
import * as sql from "../sql/api.js";
import * as cosmos from "../cosmos/api.js";

export const ENGINES = [["sql", "SQL Server - Azure SQL Database"], ["cosmos", "Azure Cosmos DB for NoSQL"]];
export const SQL_PLANS = [
  ["Basic", "Basic (dev/test)", { name: "Basic", tier: "Basic", capacity: 5 }],
  ["Standard", "Standard (S0)", { name: "S0", tier: "Standard", capacity: 10 }],
];
export const SQL_NAME_RE = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
export const COSMOS_NAME_RE = /^[a-z0-9](?:[a-z0-9-]{1,42}[a-z0-9])$/;

/** Provision per the Database tab. Returns {connectionStrings, summary:{engine,...}} to apply to the site. */
export async function provisionDatabase(d, { rg, location }) {
  if (d.engine === "cosmos") {
    if (d.cosmosChoice === "__new") {
      await cosmos.createAccount(rg, d.cosmosAccount, {
        location, kind: "GlobalDocumentDB",
        properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: location, failoverPriority: 0 }],
          consistencyPolicy: { defaultConsistencyLevel: "Session" }, capabilities: [] },
      });
    }
    const acct = d.cosmosChoice === "__new" ? d.cosmosAccount : d.cosmosChoice;
    const acctRg = d.cosmosChoice === "__new" ? rg : d.cosmosRg;
    cosmos.setActiveAccount(acct);
    await cosmos.createDatabase(d.databaseName);
    await cosmos.createContainer(d.databaseName, d.containerName || "items", "/id");
    const cs = (await cosmos.listConnectionStrings(acctRg, acct)).connectionStrings || [];
    const primary = cs.find((c) => /Primary SQL/i.test(c.description))?.connectionString || cs[0]?.connectionString;
    if (!primary) throw new Error("Cosmos DB returned no connection string for the account.");
    return {
      connectionStrings: { AZURE_COSMOS_CONNECTIONSTRING: { value: primary, type: "DocDb" } },
      summary: { engine: "cosmos", account: acct, resourceGroup: acctRg, database: d.databaseName },
    };
  }
  // Azure SQL
  const server = d.sqlChoice === "__new" ? d.sqlServer : d.sqlChoice;
  const serverRg = d.sqlChoice === "__new" ? rg : d.sqlRg;
  if (d.sqlChoice === "__new") {
    await sql.createServer(rg, server, { location, properties: { administratorLogin: d.sqlLogin, administratorLoginPassword: d.sqlPassword, version: "12.0" } });
  }
  const plan = SQL_PLANS.find(([k]) => k === d.sqlPlan) || SQL_PLANS[0];
  await sql.createDatabase(serverRg, server, d.databaseName, {
    location, sku: plan[2], properties: { requestedBackupStorageRedundancy: "Local", status: "Online", creationDate: new Date().toISOString() },
  });
  const cs = `Server=tcp:${server}.database.windows.net,1433;Initial Catalog=${d.databaseName};Persist Security Info=False;User ID=${d.sqlLogin};Password=${d.sqlPassword};MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;`;
  return {
    connectionStrings: { AZURE_SQL_CONNECTIONSTRING: { value: cs, type: "SQLAzure" } },
    summary: { engine: "sql", server, resourceGroup: serverRg, database: d.databaseName },
  };
}
