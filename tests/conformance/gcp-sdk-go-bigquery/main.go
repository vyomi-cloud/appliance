// Real cloud.google.com/go/bigquery conformance against Vyomi's BigQuery (bigquery/v2).
// Only the endpoint is changed (ENDPOINT, default http://localhost:9000).
// One [PASS]/[FAIL] line per check; non-zero exit on failure.
package main

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"cloud.google.com/go/bigquery"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/iterator"
	"google.golang.org/api/option"
)

var fails int

func chk(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fails++
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func httpCode(err error) int {
	if e, ok := err.(*googleapi.Error); ok {
		return e.Code
	}
	return 0
}

type person struct {
	ID    int64
	Name  string
	Score float64
	Paid  bool
}

func readAll(it *bigquery.RowIterator) ([][]bigquery.Value, error) {
	var out [][]bigquery.Value
	for {
		var row []bigquery.Value
		err := it.Next(&row)
		if err == iterator.Done {
			return out, nil
		}
		if err != nil {
			return out, err
		}
		out = append(out, row)
	}
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://localhost:9000"
	}
	project := os.Getenv("PROJECT")
	if project == "" {
		project = "gcp-dev"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()
	c, err := bigquery.NewClient(ctx, project, option.WithEndpoint(strings.TrimRight(ep, "/")+"/bigquery/v2/"), option.WithoutAuthentication())
	if err != nil {
		fmt.Println("[FAIL] bigquery.NewClient ::", err)
		os.Exit(1)
	}
	defer c.Close()

	dsID := fmt.Sprintf("go_bq_%d", time.Now().UnixNano()%1000000000)
	ds := c.Dataset(dsID)

	err = ds.Create(ctx, &bigquery.DatasetMetadata{Location: "US", Description: "go sdk", Labels: map[string]string{"team": "sdk"}})
	chk("Dataset.Create", err == nil, fmt.Sprint(err))
	if err != nil {
		os.Exit(1)
	}
	err = ds.Create(ctx, &bigquery.DatasetMetadata{Location: "US"})
	chk("duplicate Dataset.Create fails with 409", err != nil && httpCode(err) == 409, fmt.Sprint(err))

	md, err := ds.Metadata(ctx)
	chk("Dataset.Metadata returns location, description and labels",
		err == nil && md.Location == "US" && md.Description == "go sdk" && md.Labels["team"] == "sdk" && md.FullID == project+":"+dsID, fmt.Sprint(err, md))

	md2, err := ds.Update(ctx, bigquery.DatasetMetadataToUpdate{Description: "updated"}, md.ETag)
	chk("Dataset.Update changes the description", err == nil && md2.Description == "updated", fmt.Sprint(err))

	found := false
	dit := c.Datasets(ctx)
	for {
		d, e := dit.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			err = e
			break
		}
		if d.DatasetID == dsID {
			found = true
		}
	}
	chk("Client.Datasets lists the new dataset", found, fmt.Sprint(err))

	_, err = c.Dataset("go_bq_missing_ds").Metadata(ctx)
	chk("Metadata of an unknown dataset is 404", httpCode(err) == 404, fmt.Sprint(err))

	// ---- tables ----
	schema := bigquery.Schema{
		{Name: "id", Type: bigquery.IntegerFieldType, Required: true},
		{Name: "name", Type: bigquery.StringFieldType},
		{Name: "score", Type: bigquery.FloatFieldType},
		{Name: "paid", Type: bigquery.BooleanFieldType},
	}
	tbl := ds.Table("people")
	err = tbl.Create(ctx, &bigquery.TableMetadata{Schema: schema, Description: "people", Labels: map[string]string{"k": "v"}})
	chk("Table.Create with schema", err == nil, fmt.Sprint(err))
	err = tbl.Create(ctx, &bigquery.TableMetadata{Schema: schema})
	chk("duplicate Table.Create fails with 409", httpCode(err) == 409, fmt.Sprint(err))
	tm, err := tbl.Metadata(ctx)
	chk("Table.Metadata schema, type and NumRows", err == nil && len(tm.Schema) == 4 && tm.Schema[0].Type == bigquery.IntegerFieldType && tm.Schema[0].Required && tm.Type == bigquery.RegularTable && tm.NumRows == 0 && tm.Labels["k"] == "v", fmt.Sprint(err, tm))

	ins := tbl.Inserter()
	err = ins.Put(ctx, []*person{{1, "ann", 1.5, true}, {2, "bob", 2.5, false}, {3, "cy", 3.5, true}})
	chk("Inserter.Put streams rows (tabledata.insertAll)", err == nil, fmt.Sprint(err))
	err = ins.Put(ctx, []map[string]bigquery.Value{{"id": 4, "bogus": 1}})
	chk("Inserter.Put with an unknown column reports an insert error", err != nil, "no error")

	rows, err := readAll(tbl.Read(ctx))
	chk("Table.Read returns all rows via tabledata.list", err == nil && len(rows) == 3 && rows[1][1] == "bob" && rows[0][0] == int64(1) && rows[2][3] == true, fmt.Sprint(err, rows))

	tm, _ = tbl.Metadata(ctx)
	chk("NumRows reflects inserted rows", tm.NumRows == 3, fmt.Sprint(tm.NumRows))

	tm3, err := tbl.Update(ctx, bigquery.TableMetadataToUpdate{Description: "people v2"}, "")
	chk("Table.Update", err == nil && tm3.Description == "people v2", fmt.Sprint(err))

	found = false
	tit := ds.Tables(ctx)
	for {
		t, e := tit.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			err = e
			break
		}
		if t.TableID == "people" {
			found = true
		}
	}
	chk("Dataset.Tables lists the table", found, fmt.Sprint(err))

	// ---- queries ----
	q := c.Query(fmt.Sprintf("SELECT name, score FROM `%s.%s.people` WHERE paid ORDER BY id", project, dsID))
	it, err := q.Read(ctx)
	var res [][]bigquery.Value
	if err == nil {
		res, err = readAll(it)
	}
	chk("Query SELECT with WHERE/ORDER BY", err == nil && len(res) == 2 && res[0][0] == "ann" && res[1][1] == 3.5, fmt.Sprint(err, res))
	chk("query result schema carries column names and types", it != nil && len(it.Schema) == 2 && it.Schema[0].Name == "name" && it.Schema[1].Type == bigquery.FloatFieldType, "")

	q = c.Query("SELECT COUNT(*) AS n, SUM(score) AS total FROM people WHERE id > @min")
	q.DefaultDatasetID = dsID
	q.Parameters = []bigquery.QueryParameter{{Name: "min", Value: int64(1)}}
	it, err = q.Read(ctx)
	res = nil
	if err == nil {
		res, err = readAll(it)
	}
	chk("Query with a named parameter and default dataset", err == nil && len(res) == 1 && res[0][0] == int64(2) && res[0][1] == 6.0, fmt.Sprint(err, res))

	job, err := c.Query(fmt.Sprintf("INSERT INTO `%s.%s.people` (id, name, score, paid) VALUES (5, 'dee', 9.5, true)", project, dsID)).Run(ctx)
	if err == nil {
		var st *bigquery.JobStatus
		st, err = job.Wait(ctx)
		if err == nil {
			err = st.Err()
		}
	}
	chk("DML INSERT job runs to completion", err == nil, fmt.Sprint(err))
	if job != nil {
		cfg, _ := job.Config()
		_ = cfg
		st := job.LastStatus()
		chk("job.LastStatus is Done", st != nil && st.Done(), "")
	}
	rows, err = readAll(tbl.Read(ctx))
	chk("DML is visible to Table.Read", err == nil && len(rows) == 4, fmt.Sprint(err, len(rows)))

	// destination table
	dq := c.Query(fmt.Sprintf("SELECT id, name FROM `%s.%s.people` WHERE id <= 2", project, dsID))
	dq.QueryConfig.Dst = ds.Table("subset")
	dq.WriteDisposition = bigquery.WriteTruncate
	job, err = dq.Run(ctx)
	if err == nil {
		_, err = job.Wait(ctx)
	}
	chk("query with a destination table", err == nil, fmt.Sprint(err))
	sm, err := ds.Table("subset").Metadata(ctx)
	chk("destination table holds the result", err == nil && sm.NumRows == 2, fmt.Sprint(err, sm))

	// copy
	cp := ds.Table("people_copy").CopierFrom(tbl)
	job, err = cp.Run(ctx)
	if err == nil {
		_, err = job.Wait(ctx)
	}
	cm, merr := ds.Table("people_copy").Metadata(ctx)
	chk("Copier copies a table", err == nil && merr == nil && cm.NumRows == 4, fmt.Sprint(err, merr))

	// errors
	_, err = c.Query("SELEC bad").Read(ctx)
	if err == nil {
		_, err = readAll(func() *bigquery.RowIterator { i, _ := c.Query("SELEC bad").Read(ctx); return i }())
	}
	chk("syntax error fails with 400", err != nil && httpCode(err) == 400, fmt.Sprint(err))
	_, err = c.Query(fmt.Sprintf("SELECT * FROM `%s.%s.ghost`", project, dsID)).Read(ctx)
	chk("unknown table fails with 404", err != nil && httpCode(err) == 404, fmt.Sprint(err))

	// jobs list
	n := 0
	jit := c.Jobs(ctx)
	for n < 500 {
		_, e := jit.Next()
		if e != nil {
			break
		}
		n++
	}
	chk("Client.Jobs lists the jobs that ran", n > 0, fmt.Sprint(n))

	// routines
	rt := ds.Routine("add_one")
	err = rt.Create(ctx, &bigquery.RoutineMetadata{
		Type: "SCALAR_FUNCTION", Language: "SQL", Body: "x + 1",
		Arguments:  []*bigquery.RoutineArgument{{Name: "x", DataType: &bigquery.StandardSQLDataType{TypeKind: "INT64"}}},
		ReturnType: &bigquery.StandardSQLDataType{TypeKind: "INT64"},
	})
	chk("Routine.Create", err == nil, fmt.Sprint(err))
	rm, err := rt.Metadata(ctx)
	chk("Routine.Metadata", err == nil && rm.Body == "x + 1" && rm.Type == "SCALAR_FUNCTION", fmt.Sprint(err))
	chk("Routine.Delete", rt.Delete(ctx) == nil, "")

	// cleanup
	chk("Table.Delete", tbl.Delete(ctx) == nil, "")
	_, err = tbl.Metadata(ctx)
	chk("deleted table is 404", httpCode(err) == 404, fmt.Sprint(err))
	err = ds.Delete(ctx)
	chk("Dataset.Delete of a non-empty dataset fails", err != nil && httpCode(err) == 400, fmt.Sprint(err))
	chk("Dataset.DeleteWithContents", ds.DeleteWithContents(ctx) == nil, "")
	_, err = ds.Metadata(ctx)
	chk("deleted dataset is 404", httpCode(err) == 404, fmt.Sprint(err))

	if fails > 0 {
		fmt.Printf("%d check(s) failed\n", fails)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}
