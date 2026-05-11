CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_names_pair
    ON subject_names(subject_name_id, subject_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subject_addresses_pair
    ON subject_addresses(address_id, subject_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sanction_subjects_subject_id
    ON sanction_subjects(subject_id);

ALTER TABLE subject_name_embeddings
    ADD CONSTRAINT fk_sne_subject_names
    FOREIGN KEY (subject_name_id, subject_id)
    REFERENCES subject_names(subject_name_id, subject_id)
    ON DELETE CASCADE
    NOT VALID;

ALTER TABLE subject_name_embeddings
    ADD CONSTRAINT fk_sne_sanction_subjects
    FOREIGN KEY (subject_id)
    REFERENCES sanction_subjects(subject_id)
    ON DELETE CASCADE
    NOT VALID;

ALTER TABLE subject_address_embeddings
    ADD CONSTRAINT fk_sae_subject_addresses
    FOREIGN KEY (address_id, subject_id)
    REFERENCES subject_addresses(address_id, subject_id)
    ON DELETE CASCADE
    NOT VALID;

ALTER TABLE subject_address_embeddings
    ADD CONSTRAINT fk_sae_sanction_subjects
    FOREIGN KEY (subject_id)
    REFERENCES sanction_subjects(subject_id)
    ON DELETE CASCADE
    NOT VALID;

ALTER TABLE subject_name_embeddings
    VALIDATE CONSTRAINT fk_sne_subject_names;

ALTER TABLE subject_name_embeddings
    VALIDATE CONSTRAINT fk_sne_sanction_subjects;

ALTER TABLE subject_address_embeddings
    VALIDATE CONSTRAINT fk_sae_subject_addresses;

ALTER TABLE subject_address_embeddings
    VALIDATE CONSTRAINT fk_sae_sanction_subjects;