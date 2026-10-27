import com.google.api.gax.paging.Page;
import com.google.cloud.NoCredentials;
import com.google.cloud.bigquery.BigQuery;
import com.google.cloud.bigquery.BigQueryException;
import com.google.cloud.bigquery.BigQueryOptions;
import com.google.cloud.bigquery.CopyJobConfiguration;
import com.google.cloud.bigquery.Dataset;
import com.google.cloud.bigquery.DatasetId;
import com.google.cloud.bigquery.DatasetInfo;
import com.google.cloud.bigquery.Field;
import com.google.cloud.bigquery.FieldValueList;
import com.google.cloud.bigquery.InsertAllRequest;
import com.google.cloud.bigquery.InsertAllResponse;
import com.google.cloud.bigquery.Job;
import com.google.cloud.bigquery.JobId;
import com.google.cloud.bigquery.JobInfo;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.QueryParameterValue;
import com.google.cloud.bigquery.Schema;
import com.google.cloud.bigquery.StandardSQLTypeName;
import com.google.cloud.bigquery.StandardTableDefinition;
import com.google.cloud.bigquery.Table;
import com.google.cloud.bigquery.TableId;
import com.google.cloud.bigquery.TableInfo;
import com.google.cloud.bigquery.TableResult;

import java.util.List;
import java.util.Map;

/**
 * Real google-cloud-bigquery (Java) conformance against Vyomi's BigQuery. Only the host is
 * changed (ENDPOINT, default http://127.0.0.1:9000). One [PASS]/[FAIL] line per check; exits
 * non-zero on failure.
 *
 *   ENDPOINT=http://localhost:9000 mvn -q -B compile exec:java -Dexec.mainClass=GcpBigQueryConformance
 */
public class GcpBigQueryConformance {
  static int fails = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (!ok) fails++;
  }

  static int code(Exception e) {
    Throwable t = e;
    while (t != null) {
      if (t instanceof BigQueryException) return ((BigQueryException) t).getCode();
      t = t.getCause();
    }
    return 0;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "gcp-dev");
    String dsName = "java_bq_" + (System.currentTimeMillis() % 1000000000L);

    BigQuery bq = BigQueryOptions.newBuilder().setHost(endpoint).setProjectId(project)
        .setCredentials(NoCredentials.getInstance()).build().getService();

    // ---- datasets ----
    try {
      Dataset ds = bq.create(DatasetInfo.newBuilder(dsName).setLocation("US").setDescription("java sdk")
          .setLabels(Map.of("team", "sdk")).build());
      check("create dataset", ds != null && ds.getDatasetId().getDataset().equals(dsName) && "US".equals(ds.getLocation()), String.valueOf(ds));
    } catch (Exception e) { check("create dataset", false, e.toString()); return; }

    try {
      bq.create(DatasetInfo.newBuilder(dsName).build());
      check("duplicate dataset fails with 409", false, "no error");
    } catch (Exception e) { check("duplicate dataset fails with 409", code(e) == 409, e.toString()); }

    Dataset got = bq.getDataset(dsName);
    check("get dataset returns description and labels", got != null && "java sdk".equals(got.getDescription()) && "sdk".equals(got.getLabels().get("team")), String.valueOf(got));
    check("get unknown dataset returns null", bq.getDataset("java_bq_missing_ds") == null, "");
    Dataset upd = bq.update(got.toBuilder().setDescription("updated").build());
    check("update dataset description", "updated".equals(upd.getDescription()), String.valueOf(upd.getDescription()));
    boolean listed = false;
    for (Dataset d : bq.listDatasets(project).iterateAll()) listed |= d.getDatasetId().getDataset().equals(dsName);
    check("listDatasets contains the dataset", listed, "");

    // ---- tables ----
    Schema schema = Schema.of(
        Field.newBuilder("id", StandardSQLTypeName.INT64).setMode(Field.Mode.REQUIRED).build(),
        Field.of("name", StandardSQLTypeName.STRING), Field.of("score", StandardSQLTypeName.FLOAT64),
        Field.of("paid", StandardSQLTypeName.BOOL));
    TableId tid = TableId.of(project, dsName, "people");
    try {
      Table t = bq.create(TableInfo.newBuilder(tid, StandardTableDefinition.of(schema)).setDescription("people").build());
      check("create table with schema", t != null && t.getDefinition().getSchema().getFields().size() == 4, String.valueOf(t));
    } catch (Exception e) { check("create table with schema", false, e.toString()); return; }
    try {
      bq.create(TableInfo.of(tid, StandardTableDefinition.of(schema)));
      check("duplicate table fails with 409", false, "no error");
    } catch (Exception e) { check("duplicate table fails with 409", code(e) == 409, e.toString()); }
    Table t = bq.getTable(tid);
    check("getTable schema types", t != null && t.getDefinition().getSchema().getFields().get(0).getType().getStandardType() == StandardSQLTypeName.INT64
        && t.getDefinition().getSchema().getFields().get(0).getMode() == Field.Mode.REQUIRED, String.valueOf(t));

    InsertAllResponse ins = bq.insertAll(InsertAllRequest.newBuilder(tid)
        .addRow(Map.of("id", 1, "name", "ann", "score", 1.5, "paid", true))
        .addRow(Map.of("id", 2, "name", "bob", "score", 2.5, "paid", false))
        .addRow(Map.of("id", 3, "name", "cy", "score", 3.5, "paid", true)).build());
    check("insertAll streams 3 rows", !ins.hasErrors(), String.valueOf(ins.getInsertErrors()));
    InsertAllResponse bad = bq.insertAll(InsertAllRequest.newBuilder(tid).addRow(Map.of("id", 9, "bogus", 1)).build());
    check("insertAll with an unknown column reports insertErrors", bad.hasErrors(), "");

    TableResult data = bq.listTableData(tid, schema);
    int n = 0; String second = "";
    for (FieldValueList r : data.iterateAll()) { if (n == 1) second = r.get("name").getStringValue(); n++; }
    check("listTableData returns the rows", n == 3 && second.equals("bob") && data.getTotalRows() == 3, n + " " + second);

    boolean tl = false;
    for (Table x : bq.listTables(DatasetId.of(project, dsName)).iterateAll()) tl |= x.getTableId().getTable().equals("people");
    check("listTables contains the table", tl, "");

    // ---- queries ----
    try {
      TableResult res = bq.query(QueryJobConfiguration.newBuilder(
          "SELECT name, score FROM `" + project + "." + dsName + ".people` WHERE paid ORDER BY id").build());
      int rows = 0; String first = "";
      for (FieldValueList r : res.iterateAll()) { if (rows == 0) first = r.get("name").getStringValue(); rows++; }
      check("query SELECT with WHERE/ORDER BY", rows == 2 && first.equals("ann"), rows + " " + first);
      check("query result schema", res.getSchema().getFields().size() == 2 && res.getSchema().getFields().get(1).getType().getStandardType() == StandardSQLTypeName.FLOAT64, String.valueOf(res.getSchema()));
    } catch (Exception e) { check("query SELECT with WHERE/ORDER BY", false, e.toString()); }

    try {
      TableResult res = bq.query(QueryJobConfiguration.newBuilder("SELECT COUNT(*) AS n, SUM(score) AS total FROM people WHERE id > @min")
          .setDefaultDataset(DatasetId.of(project, dsName)).setUseLegacySql(false)
          .addNamedParameter("min", QueryParameterValue.int64(1)).build());
      FieldValueList r = res.iterateAll().iterator().next();
      check("query with a named parameter and default dataset", r.get("n").getLongValue() == 2 && r.get("total").getDoubleValue() == 6.0, r.toString());
    } catch (Exception e) { check("query with a named parameter and default dataset", false, e.toString()); }

    try {
      JobId jid = JobId.of(project, "java_bq_job_" + System.currentTimeMillis());
      Job job = bq.create(JobInfo.newBuilder(QueryJobConfiguration.of(
          "INSERT INTO `" + project + "." + dsName + ".people` (id, name, score, paid) VALUES (5, 'dee', 9.5, true)")).setJobId(jid).build());
      job = job.waitFor();
      check("DML job completes", job != null && job.isDone() && job.getStatus().getError() == null, String.valueOf(job));
      check("getJob returns the job", bq.getJob(jid) != null && bq.getJob(jid).isDone(), "");
      long affected = ((com.google.cloud.bigquery.JobStatistics.QueryStatistics) job.getStatistics()).getNumDmlAffectedRows();
      check("DML numDmlAffectedRows is 1", affected == 1, String.valueOf(affected));
    } catch (Exception e) { check("DML job completes", false, e.toString()); }

    try {
      Job job = bq.create(JobInfo.of(CopyJobConfiguration.of(TableId.of(project, dsName, "people_copy"), tid))).waitFor();
      Table cp = bq.getTable(dsName, "people_copy");
      check("copy job copies the table", job.getStatus().getError() == null && cp != null && cp.getNumRows().longValue() == 4, String.valueOf(cp));
    } catch (Exception e) { check("copy job copies the table", false, e.toString()); }

    try {
      bq.query(QueryJobConfiguration.of("SELEC bad"));
      check("syntax error fails with 400", false, "no error");
    } catch (Exception e) { check("syntax error fails with 400", code(e) == 400 || e.toString().toLowerCase().contains("syntax"), e.toString()); }
    try {
      bq.query(QueryJobConfiguration.of("SELECT * FROM `" + project + "." + dsName + ".ghost`"));
      check("unknown table query fails", false, "no error");
    } catch (Exception e) { check("unknown table query fails", code(e) == 404 || e.toString().contains("Not found"), e.toString()); }

    int jobs = 0;
    for (Job j : bq.listJobs().iterateAll()) { jobs++; if (jobs > 50) break; }
    check("listJobs returns jobs", jobs > 0, String.valueOf(jobs));

    // ---- cleanup ----
    check("delete table", bq.delete(tid), "");
    check("deleting it again returns false", !bq.delete(tid), "");
    try {
      bq.delete(DatasetId.of(project, dsName));
      check("delete non-empty dataset fails", false, "no error");
    } catch (Exception e) { check("delete non-empty dataset fails", code(e) == 400, e.toString()); }
    check("delete dataset with contents", bq.delete(DatasetId.of(project, dsName), BigQuery.DatasetDeleteOption.deleteContents()), "");
    check("dataset is gone", bq.getDataset(dsName) == null, "");

    if (fails > 0) { System.out.println(fails + " check(s) failed"); System.exit(1); }
    System.out.println("all checks passed");
  }
}
