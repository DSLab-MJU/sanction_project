CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS subject_name_embeddings (
    embedding_id      bigserial PRIMARY KEY,
    subject_name_id   char(36) NOT NULL,
    subject_id        char(36) NOT NULL,
    field_name        text NOT NULL,
    raw_text          text NOT NULL,
    normalized_text   text NOT NULL,
    model_name        text NOT NULL DEFAULT 'sentence-transformers/all-mpnet-base-v2',
    embedding         vector(768) NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_subject_name_embeddings UNIQUE (subject_name_id, field_name),
    CONSTRAINT ck_subject_name_embeddings_field
        CHECK (field_name IN ('full_name', 'non_latin_name'))
);
CREATE TABLE IF NOT EXISTS subject_address_embeddings (
    embedding_id      bigserial PRIMARY KEY,
    address_id        char(36) NOT NULL,
    subject_id        char(36) NOT NULL,
    field_name        text NOT NULL,
    raw_text          text NOT NULL,
    normalized_text   text NOT NULL,
    model_name        text NOT NULL DEFAULT 'sentence-transformers/all-mpnet-base-v2',
    embedding         vector(768) NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_subject_address_embeddings UNIQUE (address_id, field_name),
    CONSTRAINT ck_subject_address_embeddings_field
        CHECK (field_name IN ('address_full_raw'))
);

CREATE INDEX IF NOT EXISTS idx_sne_subject_id
    ON subject_name_embeddings(subject_id);

CREATE INDEX IF NOT EXISTS idx_sne_field_name
    ON subject_name_embeddings(field_name);

CREATE INDEX IF NOT EXISTS idx_sae_subject_id
    ON subject_address_embeddings(subject_id);