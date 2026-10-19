package main

import (
	"bufio"
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// DumpCleaner cleans Postgres schema/data dumps to make them portable from
// Postgres 17 (Azure) into Vyomi's Postgres 16 server (spec R4).
type DumpCleaner struct {
	RemovedCount int
	LogLines     []string
	Extensions   []string
}

// CleanSQL analyzes and cleans a SQL dump string, returning the cleaned SQL
// and recording removed statements in the cleaner log.
func (dc *DumpCleaner) CleanSQL(sqlContent string) string {
	dc.RemovedCount = 0
	dc.LogLines = nil
	dc.Extensions = nil

	extSet := make(map[string]bool)

	// Regex patterns for statements to remove
	reCreateExt := regexp.MustCompile(`(?i)^\s*CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?["']?([a-zA-Z0-9_\-]+)["']?`)
	reCommentExt := regexp.MustCompile(`(?i)^\s*COMMENT\s+ON\s+EXTENSION\b`)
	reAlterOwner := regexp.MustCompile(`(?i)^\s*ALTER\s+.*?\s+OWNER\s+TO\b`)
	reAzureRole := regexp.MustCompile(`(?i)^\s*(GRANT|REVOKE|ALTER\s+DEFAULT\s+PRIVILEGES)\b.*?\bazure[a-zA-Z0-9_]*\b`)
	rePublicSchemaCreate := regexp.MustCompile(`(?i)^\s*CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?public\b`)
	rePublicSchemaComment := regexp.MustCompile(`(?i)^\s*COMMENT\s+ON\s+SCHEMA\s+public\b`)
	reTxTimeout := regexp.MustCompile(`(?i)^\s*SET\s+transaction_timeout\b`)
	reMaintainPriv := regexp.MustCompile(`(?i)^\s*(GRANT|REVOKE)\b.*?\bMAINTAIN\b`)

	scanner := bufio.NewScanner(strings.NewReader(sqlContent))
	var outBuf bytes.Buffer

	var stmtLines []string
	inCopyBlock := false

	stripLeadingComments := func(s string) string {
		lines := strings.Split(s, "\n")
		i := 0
		for i < len(lines) {
			trimmed := strings.TrimSpace(lines[i])
			if trimmed == "" || strings.HasPrefix(trimmed, "--") {
				i++
			} else {
				break
			}
		}
		return strings.TrimSpace(strings.Join(lines[i:], "\n"))
	}

	flushStmt := func() {
		if len(stmtLines) == 0 {
			return
		}
		stmt := strings.Join(stmtLines, "\n")
		trimmedStmt := strings.TrimSpace(stmt)
		cmdOnly := stripLeadingComments(trimmedStmt)
		if cmdOnly == "" {
			outBuf.WriteString(stmt)
			outBuf.WriteString("\n")
			stmtLines = nil
			return
		}

		// Check if this statement matches any remove rule
		shouldRemove := false
		reason := ""

		if match := reCreateExt.FindStringSubmatch(cmdOnly); len(match) > 1 {
			extName := match[1]
			if !extSet[extName] {
				extSet[extName] = true
				dc.Extensions = append(dc.Extensions, extName)
			}
			shouldRemove = true
			reason = fmt.Sprintf("CREATE EXTENSION %s (pre-created by profile)", extName)
		} else if reCommentExt.MatchString(cmdOnly) {
			shouldRemove = true
			reason = "COMMENT ON EXTENSION (extension owned by superuser)"
		} else if reAlterOwner.MatchString(cmdOnly) {
			shouldRemove = true
			reason = "ALTER ... OWNER TO (all objects owned by restoring role)"
		} else if reAzureRole.MatchString(cmdOnly) {
			shouldRemove = true
			reason = "Azure-specific role grant/revoke/privilege"
		} else if rePublicSchemaCreate.MatchString(cmdOnly) {
			shouldRemove = true
			reason = "CREATE SCHEMA public (schema already exists)"
		} else if rePublicSchemaComment.MatchString(cmdOnly) {
			shouldRemove = true
			reason = "COMMENT ON SCHEMA public"
		} else if reTxTimeout.MatchString(cmdOnly) {
			shouldRemove = true
			reason = "SET transaction_timeout (Postgres 17-only syntax)"
		} else if reMaintainPriv.MatchString(cmdOnly) {
			shouldRemove = true
			reason = "MAINTAIN privilege (Postgres 17-only syntax)"
		}

		if shouldRemove {
			dc.RemovedCount++
			dc.LogLines = append(dc.LogLines, fmt.Sprintf("[REMOVED: %s]\n%s\n", reason, trimmedStmt))
		} else {
			outBuf.WriteString(stmt)
			outBuf.WriteString("\n")
		}

		stmtLines = nil
	}

	for scanner.Scan() {
		line := scanner.Text()

		// COPY stdin blocks contain raw table data which might contain semicolons
		if inCopyBlock {
			stmtLines = append(stmtLines, line)
			if line == "\\." {
				inCopyBlock = false
				flushStmt()
			}
			continue
		}

		if strings.HasPrefix(strings.TrimSpace(line), "COPY ") && strings.HasSuffix(strings.TrimSpace(line), "FROM stdin;") {
			inCopyBlock = true
			stmtLines = append(stmtLines, line)
			continue
		}

		stmtLines = append(stmtLines, line)

		// Check statement termination (ignoring comments/whitespace at end)
		trimmed := strings.TrimSpace(line)
		if strings.HasSuffix(trimmed, ";") && !strings.HasPrefix(trimmed, "--") {
			flushStmt()
		}
	}
	flushStmt()

	return outBuf.String()
}

func (c *Config) dispatchDB(args []string) int {
	if len(args) == 0 {
		c.dbUsage()
		return 2
	}

	sub := args[0]
	subArgs := args[1:]

	switch sub {
	case "dump":
		return c.runDBDump(subArgs)
	case "restore":
		return c.runDBRestore(subArgs)
	case "refresh":
		return c.runDBRefresh(subArgs)
	case "-h", "--help", "help":
		c.dbUsage()
		return 0
	default:
		fmt.Fprintf(os.Stderr, "vyomi db: unknown subcommand %q\n", sub)
		c.dbUsage()
		return 2
	}
}

func (c *Config) dbUsage() {
	fmt.Println("Usage: vyomi db <command> [options]")
	fmt.Println()
	fmt.Println("Commands:")
	fmt.Println("  dump     Export database schema and data from Postgres container")
	fmt.Println("           Options: [--app <app>] [--db <db>] [--file <out.sql>]")
	fmt.Println("  restore  Restore database schema/data with Azure/17 syntax cleaning")
	fmt.Println("           Options: [--app <app>] [--db <db>] --file <in.sql> [--dry-run]")
	fmt.Println("  refresh  Two-pass materialized view refresh and sequence reset")
	fmt.Println("           Options: [--app <app>] [--db <db>]")
}

func (c *Config) resolveDBTarget(args []string) (appName, dbName, userName string, remaining []string) {
	for i := 0; i < len(args); i++ {
		if args[i] == "--app" && i+1 < len(args) {
			appName = args[i+1]
			i++
		} else if strings.HasPrefix(args[i], "--app=") {
			appName = strings.TrimPrefix(args[i], "--app=")
		} else if args[i] == "--db" && i+1 < len(args) {
			dbName = args[i+1]
			i++
		} else if strings.HasPrefix(args[i], "--db=") {
			dbName = strings.TrimPrefix(args[i], "--db=")
		} else if args[i] == "--user" && i+1 < len(args) {
			userName = args[i+1]
			i++
		} else if strings.HasPrefix(args[i], "--user=") {
			userName = strings.TrimPrefix(args[i], "--user=")
		} else {
			remaining = append(remaining, args[i])
		}
	}

	// If app name is given but dbName is not, inspect app profile
	if appName != "" && dbName == "" {
		_, app, err := c.resolveAppRepo(appName)
		if err == nil && app.Resources != nil {
			if pgRes, ok := app.Resources["postgres"].(map[string]any); ok {
				for name, cfg := range pgRes {
					dbName = name
					if cfgMap, ok := cfg.(map[string]any); ok {
						if u, ok := cfgMap["user"].(string); ok && u != "" {
							userName = u
						}
					}
					break
				}
			}
		}
		if dbName == "" {
			dbName = appName
		}
	}

	if dbName == "" {
		dbName = "postgres"
	}
	if userName == "" {
		if appName != "" {
			userName = appName
		} else if dbName != "postgres" {
			userName = dbName
		} else {
			userName = "postgres"
		}
	}

	return appName, dbName, userName, remaining
}

// runDBDump implements `vyomi db dump`
func (c *Config) runDBDump(args []string) int {
	_, dbName, _, rem := c.resolveDBTarget(args)

	outFile := fmt.Sprintf("%s-dump.sql", dbName)
	for i := 0; i < len(rem); i++ {
		if rem[i] == "--file" && i+1 < len(rem) {
			outFile = rem[i+1]
			i++
		} else if strings.HasPrefix(rem[i], "--file=") {
			outFile = strings.TrimPrefix(rem[i], "--file=")
		}
	}

	tmpContainerFile := fmt.Sprintf("/tmp/vyomi-dump-%d.sql", time.Now().UnixNano())

	fmt.Printf("Dumping database %q...\n", dbName)
	dumpCmd := []string{"pg_dump", "-U", "postgres", "-d", dbName, "-f", tmpContainerFile}
	out, err := c.backendExec("postgres", dumpCmd, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi db dump failed: %v\nOutput: %s\n", err, out)
		return 1
	}

	absOut, _ := filepath.Abs(outFile)
	if err := c.backendCopyOut("postgres", tmpContainerFile, absOut); err != nil {
		fmt.Fprintf(os.Stderr, "failed to copy dump file to host: %v\n", err)
		return 1
	}

	// Clean up container tmp file
	_, _ = c.backendExec("postgres", []string{"rm", "-f", tmpContainerFile}, nil)

	fi, err := os.Stat(absOut)
	if err == nil {
		fmt.Printf("✓ Database %q dumped successfully to %s (%d bytes)\n", dbName, outFile, fi.Size())
	} else {
		fmt.Printf("✓ Database %q dumped successfully to %s\n", dbName, outFile)
	}

	return 0
}

// runDBRefresh implements `vyomi db refresh`
func (c *Config) runDBRefresh(args []string) int {
	_, dbName, _, _ := c.resolveDBTarget(args)

	fmt.Printf("Refreshing database %q (materialized views and sequence resets)...\n", dbName)

	refreshSQL := `
DO $$
DECLARE
    r RECORD;
BEGIN
    -- Pass 1: best-effort refresh (catch errors so dependent views can retry in pass 2)
    FOR r IN (
        SELECT schemaname, matviewname
        FROM pg_matviews
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    ) LOOP
        BEGIN
            EXECUTE format('REFRESH MATERIALIZED VIEW %I.%I', r.schemaname, r.matviewname);
        EXCEPTION WHEN OTHERS THEN
            -- Ignored in pass 1: will be retried in pass 2 after dependencies are refreshed
            NULL;
        END;
    END LOOP;

    -- Pass 2: resolve inter-view dependencies (strict: any error here will raise)
    FOR r IN (
        SELECT schemaname, matviewname
        FROM pg_matviews
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    ) LOOP
        EXECUTE format('REFRESH MATERIALIZED VIEW %I.%I', r.schemaname, r.matviewname);
    END LOOP;
END $$;
`
	out, err := c.backendExec("postgres", []string{"psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", dbName, "-c", refreshSQL}, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi db refresh: failed to refresh materialized views: %v\nOutput: %s\n", err, out)
		return 1
	}

	resetSeqSQL := `
DO $$
DECLARE
    rec RECORD;
    max_val BIGINT;
BEGIN
    FOR rec IN (
        SELECT
            s.relname AS seq_name,
            n.nspname AS schema_name,
            t.relname AS table_name,
            a.attname AS col_name
        FROM pg_class s
        JOIN pg_namespace n ON n.oid = s.relnamespace
        JOIN pg_depend d ON d.objid = s.oid AND d.classid = 'pg_class'::regclass AND d.refclassid = 'pg_class'::regclass
        JOIN pg_class t ON t.oid = d.refobjid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE s.relkind = 'S'
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ) LOOP
        EXECUTE format('SELECT COALESCE(MAX(%I), 0) FROM %I.%I', rec.col_name, rec.schema_name, rec.table_name) INTO max_val;
        IF max_val > 0 THEN
            EXECUTE format('SELECT setval(''%I.%I'', %s, true)', rec.schema_name, rec.seq_name, max_val);
        ELSE
            EXECUTE format('SELECT setval(''%I.%I'', 1, false)', rec.schema_name, rec.seq_name);
        END IF;
    END LOOP;
END $$;
`
	out, err = c.backendExec("postgres", []string{"psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", dbName, "-c", resetSeqSQL}, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi db refresh: failed to reset sequences: %v\nOutput: %s\n", err, out)
		return 1
	}

	fmt.Printf("✓ Database %q refreshed successfully (materialized views refreshed; sequences reset).\n", dbName)
	return 0
}

// runDBRestore implements `vyomi db restore`
func (c *Config) runDBRestore(args []string) int {
	_, dbName, userName, rem := c.resolveDBTarget(args)

	var inFile string
	dryRun := false

	for i := 0; i < len(rem); i++ {
		if rem[i] == "--file" && i+1 < len(rem) {
			inFile = rem[i+1]
			i++
		} else if strings.HasPrefix(rem[i], "--file=") {
			inFile = strings.TrimPrefix(rem[i], "--file=")
		} else if rem[i] == "--dry-run" {
			dryRun = true
		}
	}

	if inFile == "" {
		fmt.Fprintln(os.Stderr, "error: --file <dump.sql> is required for vyomi db restore")
		c.dbUsage()
		return 2
	}

	rawBytes, err := os.ReadFile(inFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error reading dump file %s: %v\n", inFile, err)
		return 1
	}

	cleaner := &DumpCleaner{}
	cleanedSQL := cleaner.CleanSQL(string(rawBytes))

	logFile := inFile + ".clean.log"
	logContent := strings.Join(cleaner.LogLines, "\n")
	_ = os.WriteFile(logFile, []byte(logContent), 0644)

	fmt.Printf("Cleaned dump: removed %d statements. Cleaning log written to %s\n", cleaner.RemovedCount, logFile)

	// Pre-restore extension check (Spec R4):
	// Ensure all extensions created by dump are installed in target db
	installedExtOut, err := c.backendExec("postgres", []string{
		"psql", "-U", "postgres", "-d", dbName, "-t", "-A", "-c", "SELECT extname FROM pg_extension;",
	}, nil)
	if err == nil {
		installedMap := make(map[string]bool)
		for _, ext := range strings.Fields(installedExtOut) {
			installedMap[strings.TrimSpace(ext)] = true
		}
		for _, requiredExt := range cleaner.Extensions {
			if !installedMap[requiredExt] {
				fmt.Fprintf(os.Stderr, "error: extension %q required by dump is not installed in database %s\n", requiredExt, dbName)
				fmt.Fprintf(os.Stderr, "hint: add %s to the profile's extensions and run vyomi app provision\n", requiredExt)
				return 1
			}
		}
	}

	// Prepare temp cleaned SQL file on host
	tmpHostFile := filepath.Join(os.TempDir(), fmt.Sprintf("vyomi-clean-%d.sql", time.Now().UnixNano()))
	if err := os.WriteFile(tmpHostFile, []byte(cleanedSQL), 0600); err != nil {
		fmt.Fprintf(os.Stderr, "error staging cleaned SQL: %v\n", err)
		return 1
	}
	defer os.Remove(tmpHostFile)

	tmpContainerFile := fmt.Sprintf("/tmp/vyomi-restore-%d.sql", time.Now().UnixNano())
	if err := c.backendCopyIn("postgres", tmpHostFile, tmpContainerFile); err != nil {
		fmt.Fprintf(os.Stderr, "failed to copy cleaned SQL to Postgres container: %v\n", err)
		return 1
	}
	defer func() {
		_, _ = c.backendExec("postgres", []string{"rm", "-f", tmpContainerFile}, nil)
	}()

	if dryRun {
		scratchDB := fmt.Sprintf("vyomi_scratch_%d", time.Now().UnixNano()%1000000)
		fmt.Printf("Performing --dry-run restore into scratch database %q...\n", scratchDB)

		// Create scratch database owned by userName
		createCmd := fmt.Sprintf(`CREATE DATABASE "%s" OWNER "%s";`, scratchDB, userName)
		if out, err := c.backendExec("postgres", []string{"psql", "-U", "postgres", "-c", createCmd}, nil); err != nil {
			fmt.Fprintf(os.Stderr, "dry-run: failed to create scratch database: %v (output: %s)\n", err, out)
			return 1
		}
		defer func() {
			dropCmd := fmt.Sprintf(`DROP DATABASE IF EXISTS "%s";`, scratchDB)
			_, _ = c.backendExec("postgres", []string{"psql", "-U", "postgres", "-c", dropCmd}, nil)
		}()

		// Pre-install existing extensions in scratch database
		for _, ext := range cleaner.Extensions {
			extCmd := fmt.Sprintf(`CREATE EXTENSION IF NOT EXISTS "%s";`, ext)
			_, _ = c.backendExec("postgres", []string{"psql", "-U", "postgres", "-d", scratchDB, "-c", extCmd}, nil)
		}

		// Restore into scratch database as role userName
		restoreCmd := []string{"psql", "-v", "ON_ERROR_STOP=1", "-U", userName, "-d", scratchDB, "-f", tmpContainerFile}
		out, err := c.backendExec("postgres", restoreCmd, nil)
		if err != nil {
			fmt.Fprintf(os.Stderr, "dry-run restore failed: %v\nOutput: %s\n", err, out)
			return 1
		}

		fmt.Println("✓ Dry-run restore succeeded. Dump is clean, compatible, and ready for restore.")
		return 0
	}

	// Real restore into target db as role userName
	fmt.Printf("Restoring into database %q as role %q...\n", dbName, userName)
	restoreCmd := []string{"psql", "-v", "ON_ERROR_STOP=1", "-U", userName, "-d", dbName, "-f", tmpContainerFile}
	out, err := c.backendExec("postgres", restoreCmd, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "vyomi db restore failed: %v\nOutput: %s\n", err, out)
		return 1
	}

	fmt.Printf("✓ Database %q restored successfully as role %q\n", dbName, userName)
	return 0
}
