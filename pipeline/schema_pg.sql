-- =========================================================
-- Sanctions Common Schema DDL (PostgreSQL version)
-- =========================================================

BEGIN;

-- ---------------------------------------------------------
-- Optional cleanup (uncomment if needed)
-- ---------------------------------------------------------
-- DROP TABLE IF EXISTS subject_update_events CASCADE;
-- DROP TABLE IF EXISTS subject_source_records CASCADE;
-- DROP TABLE IF EXISTS subject_notes CASCADE;
-- DROP TABLE IF EXISTS subject_measures CASCADE;
-- DROP TABLE IF EXISTS subject_regulations CASCADE;
-- DROP TABLE IF EXISTS subject_programs CASCADE;
-- DROP TABLE IF EXISTS subject_vessel_details CASCADE;
-- DROP TABLE IF EXISTS subject_relationships CASCADE;
-- DROP TABLE IF EXISTS subject_contacts CASCADE;
-- DROP TABLE IF EXISTS subject_nationalities CASCADE;
-- DROP TABLE IF EXISTS subject_birth_places CASCADE;
-- DROP TABLE IF EXISTS subject_birth_dates CASCADE;
-- DROP TABLE IF EXISTS subject_identifiers CASCADE;
-- DROP TABLE IF EXISTS subject_addresses CASCADE;
-- DROP TABLE IF EXISTS subject_names CASCADE;
-- DROP TABLE IF EXISTS sanction_subjects CASCADE;

-- ---------------------------------------------------------
-- 1. sanction_subjects
-- ---------------------------------------------------------
CREATE TABLE sanction_subjects (
    subject_id CHAR(36) NOT NULL,
    source_system VARCHAR(20) NOT NULL,
    source_dataset VARCHAR(50) NOT NULL,
    subject_type VARCHAR(20) NOT NULL,
    subject_type_raw TEXT NULL,
    subject_type_code_raw TEXT NULL,
    primary_name TEXT NOT NULL,
    title TEXT NULL,
    gender VARCHAR(50) NULL,
    function_role TEXT NULL,
    designation_date DATE NULL,
    designation_details_raw TEXT NULL,
    designation_source_raw TEXT NULL,
    entity_subtype_raw TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_sanction_subjects PRIMARY KEY (subject_id)
);

CREATE INDEX idx_sanction_subjects_source
    ON sanction_subjects (source_system, source_dataset);

CREATE INDEX idx_sanction_subjects_type
    ON sanction_subjects (subject_type);

-- ---------------------------------------------------------
-- 2. subject_names
-- ---------------------------------------------------------
CREATE TABLE subject_names (
    subject_name_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    full_name TEXT NOT NULL,
    name_part_1 TEXT NULL,
    name_part_2 TEXT NULL,
    name_part_3 TEXT NULL,
    name_part_4 TEXT NULL,
    name_part_5 TEXT NULL,
    name_part_6 TEXT NULL,
    name_type VARCHAR(30) NOT NULL,
    alias_strength TEXT NULL,
    name_quality TEXT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    non_latin_name TEXT NULL,
    non_latin_script_type TEXT NULL,
    non_latin_language TEXT NULL,
    language_code VARCHAR(20) NULL,
    note TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_names PRIMARY KEY (subject_name_id),
    CONSTRAINT fk_subject_names_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_names_subject
    ON subject_names (subject_id);

-- ---------------------------------------------------------
-- 3. subject_addresses
-- ---------------------------------------------------------
CREATE TABLE subject_addresses (
    address_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    address_full_raw TEXT NULL,
    address_line_1 TEXT NULL,
    address_line_2 TEXT NULL,
    address_line_3 TEXT NULL,
    address_line_4 TEXT NULL,
    address_line_5 TEXT NULL,
    address_line_6 TEXT NULL,
    street TEXT NULL,
    po_box TEXT NULL,
    city TEXT NULL,
    state_province TEXT NULL,
    region TEXT NULL,
    place TEXT NULL,
    postal_code TEXT NULL,
    country_code VARCHAR(10) NULL,
    country_name TEXT NULL,
    as_at_listing_time TEXT NULL,
    contact_info TEXT NULL,
    note TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_addresses PRIMARY KEY (address_id),
    CONSTRAINT fk_subject_addresses_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_addresses_subject
    ON subject_addresses (subject_id);

CREATE INDEX idx_subject_addresses_country_code
    ON subject_addresses (country_code);

-- ---------------------------------------------------------
-- 4. subject_identifiers
-- ---------------------------------------------------------
CREATE TABLE subject_identifiers (
    identifier_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    identifier_type VARCHAR(50) NOT NULL,
    identifier_value TEXT NOT NULL,
    identifier_value_latin TEXT NULL,
    name_on_document TEXT NULL,
    issued_by TEXT NULL,
    issuing_country_code VARCHAR(10) NULL,
    issuing_country_name TEXT NULL,
    issued_date DATE NULL,
    valid_from DATE NULL,
    valid_to DATE NULL,
    is_diplomatic BOOLEAN NULL,
    is_known_expired BOOLEAN NULL,
    is_known_false BOOLEAN NULL,
    is_reported_lost BOOLEAN NULL,
    is_revoked_by_issuer BOOLEAN NULL,
    additional_information TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_identifiers PRIMARY KEY (identifier_id),
    CONSTRAINT fk_subject_identifiers_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_identifiers_subject
    ON subject_identifiers (subject_id);

CREATE INDEX idx_subject_identifiers_type
    ON subject_identifiers (identifier_type);

-- ---------------------------------------------------------
-- 5. subject_birth_dates
-- ---------------------------------------------------------
CREATE TABLE subject_birth_dates (
    birth_date_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    birth_date DATE NULL,
    day INT NULL,
    month INT NULL,
    year INT NULL,
    year_from INT NULL,
    year_to INT NULL,
    circa_flag BOOLEAN NULL,
    calendar_type TEXT NULL,
    date_type_raw TEXT NULL,
    is_incomplete BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_birth_dates PRIMARY KEY (birth_date_id),
    CONSTRAINT fk_subject_birth_dates_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_birth_dates_subject
    ON subject_birth_dates (subject_id);

CREATE INDEX idx_subject_birth_dates_birth_date
    ON subject_birth_dates (birth_date);

-- ---------------------------------------------------------
-- 6. subject_birth_places
-- ---------------------------------------------------------
CREATE TABLE subject_birth_places (
    birth_place_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    place TEXT NULL,
    street TEXT NULL,
    city TEXT NULL,
    state_province TEXT NULL,
    region TEXT NULL,
    postal_code TEXT NULL,
    country_code VARCHAR(10) NULL,
    country_name TEXT NULL,
    note TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_birth_places PRIMARY KEY (birth_place_id),
    CONSTRAINT fk_subject_birth_places_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_birth_places_subject
    ON subject_birth_places (subject_id);

-- ---------------------------------------------------------
-- 7. subject_nationalities
-- ---------------------------------------------------------
CREATE TABLE subject_nationalities (
    nationality_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    country_code VARCHAR(10) NULL,
    country_name TEXT NULL,
    region TEXT NULL,
    nationality_raw TEXT NULL,
    note TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_nationalities PRIMARY KEY (nationality_id),
    CONSTRAINT fk_subject_nationalities_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_nationalities_subject
    ON subject_nationalities (subject_id);

-- ---------------------------------------------------------
-- 8. subject_contacts
-- ---------------------------------------------------------
CREATE TABLE subject_contacts (
    contact_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    contact_type VARCHAR(20) NOT NULL,
    contact_value TEXT NOT NULL,
    note TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_contacts PRIMARY KEY (contact_id),
    CONSTRAINT fk_subject_contacts_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_contacts_subject
    ON subject_contacts (subject_id);

CREATE INDEX idx_subject_contacts_type
    ON subject_contacts (contact_type);

-- ---------------------------------------------------------
-- 9. subject_relationships
-- ---------------------------------------------------------
CREATE TABLE subject_relationships (
    relationship_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    relationship_type VARCHAR(50) NOT NULL,
    related_name TEXT NOT NULL,
    note TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_relationships PRIMARY KEY (relationship_id),
    CONSTRAINT fk_subject_relationships_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_relationships_subject
    ON subject_relationships (subject_id);

CREATE INDEX idx_subject_relationships_type
    ON subject_relationships (relationship_type);

-- ---------------------------------------------------------
-- 10. subject_vessel_details
-- ---------------------------------------------------------
CREATE TABLE subject_vessel_details (
    vessel_detail_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    call_sign TEXT NULL,
    imo_number TEXT NULL,
    vessel_type TEXT NULL,
    tonnage DECIMAL(18,2) NULL,
    grt DECIMAL(18,2) NULL,
    length DECIMAL(18,2) NULL,
    year_built INT NULL,
    flag_current TEXT NULL,
    flags_previous_raw TEXT NULL,
    hull_id TEXT NULL,
    owner_operator_current_raw TEXT NULL,
    owner_operator_previous_raw TEXT NULL,
    vessel_owner_raw TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_vessel_details PRIMARY KEY (vessel_detail_id),
    CONSTRAINT fk_subject_vessel_details_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_subject_vessel_details_subject UNIQUE (subject_id)
);

-- ---------------------------------------------------------
-- 11. subject_programs
-- ---------------------------------------------------------
CREATE TABLE subject_programs (
    program_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    list_family TEXT NULL,
    regime_name TEXT NULL,
    program_name TEXT NULL,
    source_component_scope TEXT NULL,
    source_component_id TEXT NULL,
    note TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_programs PRIMARY KEY (program_id),
    CONSTRAINT fk_subject_programs_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_programs_subject
    ON subject_programs (subject_id);

-- ---------------------------------------------------------
-- 12-A. subject_regulations
-- ---------------------------------------------------------
CREATE TABLE subject_regulations (
    regulation_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    regulation_scope TEXT NULL,
    regulation_type TEXT NULL,
    organisation_type TEXT NULL,
    publication_date DATE NULL,
    entry_into_force_date DATE NULL,
    number_title TEXT NULL,
    publication_url TEXT NULL,
    regulation_language TEXT NULL,
    note TEXT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_regulations PRIMARY KEY (regulation_id),
    CONSTRAINT fk_subject_regulations_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_regulations_subject
    ON subject_regulations (subject_id);

-- ---------------------------------------------------------
-- 12-B. subject_measures
-- ---------------------------------------------------------
CREATE TABLE subject_measures (
    measure_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    measure_type TEXT NULL,
    measure_raw_text TEXT NOT NULL,
    severity_hint TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_measures PRIMARY KEY (measure_id),
    CONSTRAINT fk_subject_measures_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_measures_subject
    ON subject_measures (subject_id);

-- ---------------------------------------------------------
-- 12-C. subject_notes
-- ---------------------------------------------------------
CREATE TABLE subject_notes (
    note_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    note_type TEXT NOT NULL,
    note_text TEXT NOT NULL,
    source_component_id TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_notes PRIMARY KEY (note_id),
    CONSTRAINT fk_subject_notes_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_notes_subject
    ON subject_notes (subject_id);

-- ---------------------------------------------------------
-- 12-D. subject_source_records
-- ---------------------------------------------------------
CREATE TABLE subject_source_records (
    source_record_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    source_system VARCHAR(20) NOT NULL,
    source_dataset VARCHAR(50) NOT NULL,
    source_primary_id TEXT NULL,
    source_secondary_id TEXT NULL,
    source_tertiary_id TEXT NULL,
    source_component_type TEXT NULL,
    source_component_id TEXT NULL,
    file_generation_date DATE NULL,
    report_date DATE NULL,
    version_num TEXT NULL,
    list_type_raw TEXT NULL,
    sort_key TEXT NULL,
    sort_key_last_mod TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_source_records PRIMARY KEY (source_record_id),
    CONSTRAINT fk_subject_source_records_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_source_records_subject
    ON subject_source_records (subject_id);

-- ---------------------------------------------------------
-- 12-E. subject_update_events
-- ---------------------------------------------------------
CREATE TABLE subject_update_events (
    update_id CHAR(36) NOT NULL,
    subject_id CHAR(36) NOT NULL,
    update_date DATE NOT NULL,
    update_type_raw TEXT NULL,
    note TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_subject_update_events PRIMARY KEY (update_id),
    CONSTRAINT fk_subject_update_events_subject
        FOREIGN KEY (subject_id) REFERENCES sanction_subjects(subject_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_subject_update_events_subject
    ON subject_update_events (subject_id);

CREATE INDEX idx_subject_update_events_date
    ON subject_update_events (update_date);

-- ---------------------------------------------------------
-- Trigger for sanction_subjects.updated_at
-- ---------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sanction_subjects_updated_at ON sanction_subjects;

CREATE TRIGGER trg_sanction_subjects_updated_at
BEFORE UPDATE ON sanction_subjects
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMIT;
