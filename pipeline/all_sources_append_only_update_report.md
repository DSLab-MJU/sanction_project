# All Sources Append-Only Update Pipeline Report

## Scope

The all-source update pipeline covers:

```text
OFAC SDN + Consolidated
UK Sanctions List
UN Security Council Consolidated List
EU Consolidated Financial Sanctions List
```

The implemented script is:

```text
server_run_all_sources_update.sh
```

It uses the existing canonical parser:

```text
integrate_sanctions_pipeline.py
```

and the append-only loader:

```text
load_batch_append_only.sql
```

## Source Entrypoints

Default source pages:

```text
OFAC: https://sanctionslist.ofac.treas.gov/Home/static/index.html
UK:   https://www.gov.uk/government/publications/the-uk-sanctions-list
UN:   https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
EU:   https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions?locale=en
```

UN file download uses the official consolidated XML endpoint when the `main.un.org` page blocks non-browser server requests:

```text
https://scsanctions.un.org/resources/xml/en/consolidated.xml
```

EU file download uses the official EU FSF CSV v1.1 endpoint when the data.europa page does not expose a direct CSV link to a non-JavaScript client:

```text
https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw
```

## Downloaded File Layout

Each run creates:

```text
all_sources_raw_snapshots/<batch-name>/
  EU_consolidated_1_1.csv
  UK-Sanctions-List.csv
  UN_consolidatedLegacyByPRN.xml
  download_manifest.csv
  download_manifest.json
  discovery/
  ofac/
    sdn.csv
    sdn_comments.csv
    alt.csv
    add.csv
    cons_prim.csv
    cons_comments.csv
    cons_alt.csv
    cons_add.csv
```

## Generated Schema Batch

Each run writes canonical CSVs to:

```text
all_sources_update_runs/<batch-name>/
```

The local validation run using the current workspace files produced:

```text
sanction_subjects rows=32063
subject_names rows=92190
subject_addresses rows=31765
subject_identifiers rows=71701
subject_birth_dates rows=16845
subject_birth_places rows=12265
subject_nationalities rows=12407
subject_contacts rows=4380
subject_relationships rows=9694
subject_vessel_details rows=2080
subject_programs rows=47796
subject_regulations rows=23842
subject_measures rows=22156
subject_notes rows=47044
subject_source_records rows=183337
subject_update_events rows=6694
VALIDATION_OK
```

## Append-Only Load Policy

The DB loader does not update, delete, or inactivate existing rows.

It loads generated CSVs into temporary staging tables, then inserts only rows whose primary key is not already present in the target table.

Example:

```sql
INSERT INTO subject_names
SELECT s.*
FROM stg_subject_names s
WHERE NOT EXISTS (
  SELECT 1
  FROM subject_names t
  WHERE t.subject_name_id = s.subject_name_id
);
```

`subject_vessel_details` also checks `subject_id` because the DB has a unique constraint for one vessel detail row per subject.

## Server Dry Run

```bash
cd ~/sanction/pipeline

PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' \
./server_run_all_sources_update.sh --trigger manual --skip-load
```

Success condition:

```text
VALIDATION_OK
[all-sources-update] validation passed; skipping database load
```

## Server DB Load

```bash
cd ~/sanction/pipeline

PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' \
./server_run_all_sources_update.sh --trigger manual
```

The load output includes `Inserted rows by table`. Those numbers are the actual rows that did not exist in the DB and were newly inserted.

## Reusing a Downloaded Snapshot

```bash
cd ~/sanction/pipeline

./server_run_all_sources_update.sh \
  --skip-download \
  --input-dir ~/sanction/pipeline/all_sources_raw_snapshots/<batch-name> \
  --batch-name all_sources_reload_test
```

Use this for idempotency testing or for DB load testing without hitting the upstream source pages again.

## Weekly Cron

```cron
0 4 * * 1 cd /home/dslab/sanction/pipeline && PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' ./server_run_all_sources_update.sh --trigger scheduled >> /home/dslab/sanction/pipeline/all_sources_update.log 2>&1
```
