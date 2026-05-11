\set ON_ERROR_STOP on

\if :{?batch_dir}
\else
\echo 'ERROR: batch_dir variable is required. Example: -v batch_dir=/tmp/ofac_batch'
\quit 1
\endif

\echo 'Append-only loading batch from' :batch_dir
\cd :batch_dir

BEGIN;

CREATE TEMP TABLE stg_sanction_subjects      (LIKE sanction_subjects      INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_names          (LIKE subject_names          INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_addresses      (LIKE subject_addresses      INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_identifiers    (LIKE subject_identifiers    INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_birth_dates    (LIKE subject_birth_dates    INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_birth_places   (LIKE subject_birth_places   INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_nationalities  (LIKE subject_nationalities  INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_contacts       (LIKE subject_contacts       INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_relationships  (LIKE subject_relationships  INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_vessel_details (LIKE subject_vessel_details INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_programs       (LIKE subject_programs       INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_regulations    (LIKE subject_regulations    INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_measures       (LIKE subject_measures       INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_notes          (LIKE subject_notes          INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_source_records (LIKE subject_source_records INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE stg_subject_update_events  (LIKE subject_update_events  INCLUDING DEFAULTS) ON COMMIT DROP;

\copy stg_sanction_subjects      FROM 'sanction_subjects.csv'      WITH (FORMAT csv, HEADER true)
\copy stg_subject_names          FROM 'subject_names.csv'          WITH (FORMAT csv, HEADER true)
\copy stg_subject_addresses      FROM 'subject_addresses.csv'      WITH (FORMAT csv, HEADER true)
\copy stg_subject_identifiers    FROM 'subject_identifiers.csv'    WITH (FORMAT csv, HEADER true)
\copy stg_subject_birth_dates    FROM 'subject_birth_dates.csv'    WITH (FORMAT csv, HEADER true)
\copy stg_subject_birth_places   FROM 'subject_birth_places.csv'   WITH (FORMAT csv, HEADER true)
\copy stg_subject_nationalities  FROM 'subject_nationalities.csv'  WITH (FORMAT csv, HEADER true)
\copy stg_subject_contacts       FROM 'subject_contacts.csv'       WITH (FORMAT csv, HEADER true)
\copy stg_subject_relationships  FROM 'subject_relationships.csv'  WITH (FORMAT csv, HEADER true)
\copy stg_subject_vessel_details FROM 'subject_vessel_details.csv' WITH (FORMAT csv, HEADER true)
\copy stg_subject_programs       FROM 'subject_programs.csv'       WITH (FORMAT csv, HEADER true)
\copy stg_subject_regulations    FROM 'subject_regulations.csv'    WITH (FORMAT csv, HEADER true)
\copy stg_subject_measures       FROM 'subject_measures.csv'       WITH (FORMAT csv, HEADER true)
\copy stg_subject_notes          FROM 'subject_notes.csv'          WITH (FORMAT csv, HEADER true)
\copy stg_subject_source_records FROM 'subject_source_records.csv' WITH (FORMAT csv, HEADER true)
\copy stg_subject_update_events  FROM 'subject_update_events.csv'  WITH (FORMAT csv, HEADER true)

\echo 'Inserted rows by table:'
WITH inserted AS (
  INSERT INTO sanction_subjects
  SELECT s.* FROM stg_sanction_subjects s
  WHERE NOT EXISTS (SELECT 1 FROM sanction_subjects t WHERE t.subject_id = s.subject_id)
  RETURNING 1
) SELECT 'sanction_subjects' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_names
  SELECT s.* FROM stg_subject_names s
  WHERE NOT EXISTS (SELECT 1 FROM subject_names t WHERE t.subject_name_id = s.subject_name_id)
  RETURNING 1
) SELECT 'subject_names' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_addresses
  SELECT s.* FROM stg_subject_addresses s
  WHERE NOT EXISTS (SELECT 1 FROM subject_addresses t WHERE t.address_id = s.address_id)
  RETURNING 1
) SELECT 'subject_addresses' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_identifiers
  SELECT s.* FROM stg_subject_identifiers s
  WHERE NOT EXISTS (SELECT 1 FROM subject_identifiers t WHERE t.identifier_id = s.identifier_id)
  RETURNING 1
) SELECT 'subject_identifiers' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_birth_dates
  SELECT s.* FROM stg_subject_birth_dates s
  WHERE NOT EXISTS (SELECT 1 FROM subject_birth_dates t WHERE t.birth_date_id = s.birth_date_id)
  RETURNING 1
) SELECT 'subject_birth_dates' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_birth_places
  SELECT s.* FROM stg_subject_birth_places s
  WHERE NOT EXISTS (SELECT 1 FROM subject_birth_places t WHERE t.birth_place_id = s.birth_place_id)
  RETURNING 1
) SELECT 'subject_birth_places' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_nationalities
  SELECT s.* FROM stg_subject_nationalities s
  WHERE NOT EXISTS (SELECT 1 FROM subject_nationalities t WHERE t.nationality_id = s.nationality_id)
  RETURNING 1
) SELECT 'subject_nationalities' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_contacts
  SELECT s.* FROM stg_subject_contacts s
  WHERE NOT EXISTS (SELECT 1 FROM subject_contacts t WHERE t.contact_id = s.contact_id)
  RETURNING 1
) SELECT 'subject_contacts' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_relationships
  SELECT s.* FROM stg_subject_relationships s
  WHERE NOT EXISTS (SELECT 1 FROM subject_relationships t WHERE t.relationship_id = s.relationship_id)
  RETURNING 1
) SELECT 'subject_relationships' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_vessel_details
  SELECT s.* FROM stg_subject_vessel_details s
  WHERE NOT EXISTS (SELECT 1 FROM subject_vessel_details t WHERE t.vessel_detail_id = s.vessel_detail_id)
    AND NOT EXISTS (SELECT 1 FROM subject_vessel_details t WHERE t.subject_id = s.subject_id)
  RETURNING 1
) SELECT 'subject_vessel_details' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_programs
  SELECT s.* FROM stg_subject_programs s
  WHERE NOT EXISTS (SELECT 1 FROM subject_programs t WHERE t.program_id = s.program_id)
  RETURNING 1
) SELECT 'subject_programs' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_regulations
  SELECT s.* FROM stg_subject_regulations s
  WHERE NOT EXISTS (SELECT 1 FROM subject_regulations t WHERE t.regulation_id = s.regulation_id)
  RETURNING 1
) SELECT 'subject_regulations' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_measures
  SELECT s.* FROM stg_subject_measures s
  WHERE NOT EXISTS (SELECT 1 FROM subject_measures t WHERE t.measure_id = s.measure_id)
  RETURNING 1
) SELECT 'subject_measures' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_notes
  SELECT s.* FROM stg_subject_notes s
  WHERE NOT EXISTS (SELECT 1 FROM subject_notes t WHERE t.note_id = s.note_id)
  RETURNING 1
) SELECT 'subject_notes' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_source_records
  SELECT s.* FROM stg_subject_source_records s
  WHERE NOT EXISTS (SELECT 1 FROM subject_source_records t WHERE t.source_record_id = s.source_record_id)
  RETURNING 1
) SELECT 'subject_source_records' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

WITH inserted AS (
  INSERT INTO subject_update_events
  SELECT s.* FROM stg_subject_update_events s
  WHERE NOT EXISTS (SELECT 1 FROM subject_update_events t WHERE t.update_id = s.update_id)
  RETURNING 1
) SELECT 'subject_update_events' AS table_name, COUNT(*) AS inserted_rows FROM inserted;

COMMIT;

\echo 'Append-only load complete. Current row counts:'
SELECT 'sanction_subjects' AS table_name, COUNT(*) AS row_count FROM sanction_subjects
UNION ALL
SELECT 'subject_names', COUNT(*) FROM subject_names
UNION ALL
SELECT 'subject_addresses', COUNT(*) FROM subject_addresses
UNION ALL
SELECT 'subject_identifiers', COUNT(*) FROM subject_identifiers
UNION ALL
SELECT 'subject_birth_dates', COUNT(*) FROM subject_birth_dates
UNION ALL
SELECT 'subject_birth_places', COUNT(*) FROM subject_birth_places
UNION ALL
SELECT 'subject_nationalities', COUNT(*) FROM subject_nationalities
UNION ALL
SELECT 'subject_contacts', COUNT(*) FROM subject_contacts
UNION ALL
SELECT 'subject_relationships', COUNT(*) FROM subject_relationships
UNION ALL
SELECT 'subject_vessel_details', COUNT(*) FROM subject_vessel_details
UNION ALL
SELECT 'subject_programs', COUNT(*) FROM subject_programs
UNION ALL
SELECT 'subject_regulations', COUNT(*) FROM subject_regulations
UNION ALL
SELECT 'subject_measures', COUNT(*) FROM subject_measures
UNION ALL
SELECT 'subject_notes', COUNT(*) FROM subject_notes
UNION ALL
SELECT 'subject_source_records', COUNT(*) FROM subject_source_records
UNION ALL
SELECT 'subject_update_events', COUNT(*) FROM subject_update_events
ORDER BY table_name;
