-- Append-only enforcement for the audit trail.
--
-- The application is not allowed to be the only guarantee here. An audit
-- log that application code can rewrite is worth very little in exactly
-- the situation it exists for — an investigation into whether the process
-- was followed, where the application itself is what is being questioned.
--
-- These triggers make UPDATE and DELETE raise, for every role including
-- the one the application connects as. Correcting a mistaken entry means
-- appending a correcting entry, which is how a ledger has always worked.

CREATE OR REPLACE FUNCTION vbc_deny_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% on % is not permitted: this table is append-only. '
        'Record a correcting entry instead.',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION vbc_deny_mutation();

DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log;
CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION vbc_deny_mutation();

-- Score snapshots are immutable for the same reason: a decision cites one,
-- so it must still say what it said when the decision was taken. A rescore
-- appends a new row rather than editing the old one.
DROP TRIGGER IF EXISTS vendor_scores_no_update ON vendor_scores;
CREATE TRIGGER vendor_scores_no_update
    BEFORE UPDATE ON vendor_scores
    FOR EACH ROW EXECUTE FUNCTION vbc_deny_mutation();

-- Catalog versions are content-hashed snapshots. Editing one would make
-- every score that cites it a claim about rules that no longer exist.
DROP TRIGGER IF EXISTS catalog_versions_no_update ON catalog_versions;
CREATE TRIGGER catalog_versions_no_update
    BEFORE UPDATE ON catalog_versions
    FOR EACH ROW EXECUTE FUNCTION vbc_deny_mutation();

-- Decisions are the binding record. A change of mind is a new decision row
-- with its own timestamp and author, not a rewrite of the old one.
DROP TRIGGER IF EXISTS decisions_no_update ON decisions;
CREATE TRIGGER decisions_no_update
    BEFORE UPDATE ON decisions
    FOR EACH ROW EXECUTE FUNCTION vbc_deny_mutation();

-- ---------------------------------------------------------------------
-- PRIVILEGES — the other half of immutability.
--
-- Triggers stop an application bug or a careless UPDATE. They do NOT stop
-- TRUNCATE: PostgreSQL fires row-level BEFORE DELETE triggers for DELETE
-- but not for TRUNCATE, so a role with that privilege can empty the audit
-- trail with the triggers still in place. Nor do they stop the table's
-- OWNER, who can simply DROP the triggers.
--
-- So the application must connect as a role that owns nothing and holds
-- only the rights it needs. Run the block below after creating the role;
-- it is separated out because it references a role name that varies by
-- environment.
--
--   CREATE ROLE vbc_app LOGIN PASSWORD '...';
--   GRANT CONNECT ON DATABASE vbc TO vbc_app;
--   GRANT USAGE ON SCHEMA public TO vbc_app;
--
--   -- Ordinary tables: full DML.
--   GRANT SELECT, INSERT, UPDATE, DELETE ON
--       vendors, vendor_checks, vendor_check_inputs, scan_ratings,
--       vendor_manual_entries, surveillance_entries, field_visits,
--       unlocks, jobs
--       TO vbc_app;
--
--   -- Append-only tables: no UPDATE, no DELETE, no TRUNCATE.
--   GRANT SELECT, INSERT ON
--       audit_log, vendor_scores, decisions, catalog_versions
--       TO vbc_app;
--
--   -- Catalog: read-only at runtime. The seeder runs as the owner.
--   GRANT SELECT ON
--       check_definitions, scan_parameters, surveillance_parameters,
--       risk_rules, manual_field_templates
--       TO vbc_app;
--
--   GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO vbc_app;
--
-- TRUNCATE is not grantable to a non-owner by any of the above, which is
-- the point: there is no combination of privileges here that lets the
-- application empty the audit trail.
