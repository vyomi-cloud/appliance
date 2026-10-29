package main

import (
	"strings"
	"testing"
)

func TestDumpCleaner(t *testing.T) {
	sampleDump := `
--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: azure_pg_admin
--

CREATE SCHEMA public;

ALTER SCHEMA public OWNER TO azure_pg_admin;

COMMENT ON SCHEMA public IS 'standard public schema';

SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE public.documents (
    id integer NOT NULL,
    title text NOT NULL,
    embedding public.vector(3)
);

ALTER TABLE public.documents OWNER TO siftly_user;

CREATE SEQUENCE public.documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.documents_id_seq OWNER TO siftly_user;
ALTER SEQUENCE public.documents_id_seq OWNED BY public.documents.id;

COPY public.documents (id, title, embedding) FROM stdin;
1	Doc with ; semicolon	[0.1,0.2,0.3]
2	Doc with -- comment syntax	[0.4,0.5,0.6]
\.

GRANT ALL ON SCHEMA public TO azure_pg_admin;
GRANT ALL ON SCHEMA public TO PUBLIC;
REVOKE ALL ON SCHEMA public FROM azure_pg_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE azure_pg_admin IN SCHEMA public GRANT ALL ON TABLES TO azure_pg_admin;
GRANT MAINTAIN ON TABLE public.documents TO siftly_user;

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);
`

	cleaner := &DumpCleaner{}
	cleaned := cleaner.CleanSQL(sampleDump)

	// Verify extensions extracted
	if len(cleaner.Extensions) != 2 {
		t.Fatalf("expected 2 extensions extracted, got %d: %v", len(cleaner.Extensions), cleaner.Extensions)
	}
	if cleaner.Extensions[0] != "vector" || cleaner.Extensions[1] != "uuid-ossp" {
		t.Errorf("unexpected extracted extensions: %v", cleaner.Extensions)
	}

	// Verify Postgres 17 and Azure-specific statements removed
	unwanted := []string{
		"SET transaction_timeout",
		"CREATE EXTENSION IF NOT EXISTS vector",
		"CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"",
		"COMMENT ON EXTENSION vector",
		"CREATE SCHEMA public",
		"ALTER SCHEMA public OWNER TO",
		"COMMENT ON SCHEMA public",
		"ALTER TABLE public.documents OWNER TO",
		"ALTER SEQUENCE public.documents_id_seq OWNER TO",
		"GRANT ALL ON SCHEMA public TO azure_pg_admin",
		"REVOKE ALL ON SCHEMA public FROM azure_pg_admin",
		"ALTER DEFAULT PRIVILEGES FOR ROLE azure_pg_admin",
		"GRANT MAINTAIN ON TABLE",
	}

	for _, u := range unwanted {
		if strings.Contains(cleaned, u) {
			t.Errorf("cleaned SQL still contains unwanted statement: %q", u)
		}
	}

	// Verify required valid statements preserved
	wanted := []string{
		"SET statement_timeout = 0;",
		"CREATE TABLE public.documents (",
		"embedding public.vector(3)",
		"CREATE SEQUENCE public.documents_id_seq",
		"COPY public.documents (id, title, embedding) FROM stdin;",
		"1\tDoc with ; semicolon\t[0.1,0.2,0.3]",
		"2\tDoc with -- comment syntax\t[0.4,0.5,0.6]",
		"\\.",
		"GRANT ALL ON SCHEMA public TO PUBLIC;",
		"ADD CONSTRAINT documents_pkey PRIMARY KEY (id);",
	}

	for _, w := range wanted {
		if !strings.Contains(cleaned, w) {
			t.Errorf("cleaned SQL missing expected statement/content: %q", w)
		}
	}

	if cleaner.RemovedCount < 10 {
		t.Errorf("expected at least 10 removed statements, got %d", cleaner.RemovedCount)
	}
	if len(cleaner.LogLines) != cleaner.RemovedCount {
		t.Errorf("mismatch between removed count (%d) and log lines (%d)", cleaner.RemovedCount, len(cleaner.LogLines))
	}
}

func TestResolveDBTarget(t *testing.T) {
	cfg := &Config{}

	app, db, user, rem := cfg.resolveDBTarget([]string{"--db", "custom_db", "--file", "dump.sql", "--dry-run"})
	if db != "custom_db" {
		t.Errorf("expected db 'custom_db', got %q", db)
	}
	if user != "custom_db" {
		t.Errorf("expected user 'custom_db', got %q", user)
	}
	if app != "" {
		t.Errorf("expected empty app, got %q", app)
	}
	if len(rem) != 3 || rem[0] != "--file" || rem[1] != "dump.sql" || rem[2] != "--dry-run" {
		t.Errorf("unexpected remaining args: %v", rem)
	}

	// Default target when nothing passed
	app2, db2, user2, rem2 := cfg.resolveDBTarget([]string{"--dry-run"})
	if db2 != "postgres" || user2 != "postgres" || app2 != "" || len(rem2) != 1 {
		t.Errorf("unexpected defaults: app=%s db=%s user=%s rem=%v", app2, db2, user2, rem2)
	}
}
