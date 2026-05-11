# Embedding Pipeline Integration Report

## 1. Existing Embedding Implementation

Directory:

```text
embedding/
```

Files:

```text
embedding/vector_setting.sql
embedding/add_embedding_fks.sql
embedding/load_pgvector_embeddings.py
```

`vector_setting.sql` creates:

```text
subject_name_embeddings
subject_address_embeddings
```

Embedding targets:

```text
subject_names.full_name
subject_names.non_latin_name
subject_addresses.address_full_raw
```

`load_pgvector_embeddings.py` reads:

```text
subject_names.csv
subject_addresses.csv
```

and writes embeddings into PostgreSQL pgvector tables using:

```text
sentence-transformers/all-mpnet-base-v2
```

## 2. Pipeline Connection Point

Embedding must run after canonical DB insert.

Final update flow:

```text
source download
-> canonical CSV generation
-> validation
-> append-only DB insert
-> pgvector table setup
-> embedding generation
-> embedding upsert
```

The reason is that embedding rows reference IDs from:

```text
subject_names
subject_addresses
sanction_subjects
```

Those source rows must exist in DB before embeddings are inserted.

## 3. Implemented Changes

`embedding/load_pgvector_embeddings.py` now accepts the current batch directory through environment variables:

```text
BASE_DIR
BATCH_DIR
```

Default behavior is preserved:

```text
~/sanction/integrated_schema_batch_deploy
```

Additional environment variables:

```text
EMBEDDING_MODEL_NAME
EMBEDDING_BATCH_SIZE
EMBEDDING_LOCAL_FILES_ONLY
```

`server_run_all_sources_update.sh` now runs embedding after DB load by default.

`server_run_ofac_update.sh` also runs embedding after DB load by default.

New skip flag:

```text
--skip-embedding
```

Use it when you want to test DB load without running the embedding model.

## 4. Server Files To Upload

Upload the updated scripts and the embedding directory:

```bash
scp -P 1004 \
  integrate_sanctions_pipeline.py \
  ofac_remark_prefix_mapper.py \
  validate_integrated_batch.py \
  load_batch_append_only.sql \
  server_run_all_sources_update.sh \
  server_run_ofac_update.sh \
  dslab@classnet.mju.ac.kr:~/sanction/pipeline/

scp -P 1004 -r embedding \
  dslab@classnet.mju.ac.kr:~/sanction/pipeline/
```

Server permission:

```bash
cd ~/sanction/pipeline
chmod +x server_run_all_sources_update.sh
chmod +x server_run_ofac_update.sh
```

## 5. Server Prerequisite Checks

Python package check:

```bash
python3 - <<'PY'
import pandas
import psycopg
import sentence_transformers
import tqdm
print("embedding python deps ok")
PY
```

Model cache check:

```bash
python3 - <<'PY'
from sentence_transformers import SentenceTransformer
SentenceTransformer("sentence-transformers/all-mpnet-base-v2", local_files_only=True)
print("embedding model cache ok")
PY
```

If the model is not cached and the server can download models:

```bash
EMBEDDING_LOCAL_FILES_ONLY=false python3 - <<'PY'
from sentence_transformers import SentenceTransformer
SentenceTransformer("sentence-transformers/all-mpnet-base-v2", local_files_only=False)
print("embedding model downloaded")
PY
```

PostgreSQL host connection check for the embedding script:

```bash
python3 - <<'PY'
import psycopg
conn = psycopg.connect(host="localhost", port="5432", dbname="sanction", user="dslab", password="")
conn.close()
print("postgres host connection ok")
PY
```

If this fails, check whether the Docker container exposes port 5432:

```bash
docker port sanction-postgres 5432
```

If the mapped port is different, pass it with:

```text
EMBEDDING_PGPORT=<mapped-port>
```

## 6. One-Time pgvector Setup

The automatic script runs `vector_setting.sql` before embedding, so normally this step is automatic:

```text
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS subject_name_embeddings ...
CREATE TABLE IF NOT EXISTS subject_address_embeddings ...
```

Manual setup command:

```bash
docker cp ~/sanction/pipeline/embedding/vector_setting.sql sanction-postgres:/tmp/vector_setting.sql
docker exec -i sanction-postgres psql -U dslab -d sanction -f /tmp/vector_setting.sql
```

`add_embedding_fks.sql` is not run automatically because it is not idempotent. Run it only once after confirming the embedding tables and base tables are loaded:

```bash
docker cp ~/sanction/pipeline/embedding/add_embedding_fks.sql sanction-postgres:/tmp/add_embedding_fks.sql
docker exec -i sanction-postgres psql -U dslab -d sanction -f /tmp/add_embedding_fks.sql
```

## 7. Test Without Embedding

Download, parse, validate only:

```bash
cd ~/sanction/pipeline

PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:kghkfkd@gmail.com)' \
./server_run_all_sources_update.sh --trigger manual --skip-load
```

DB load without embedding:

```bash
./server_run_all_sources_update.sh \
  --skip-download \
  --input-dir ~/sanction/pipeline/all_sources_raw_snapshots/<batch-name> \
  --batch-name all_sources_load_without_embedding_test \
  --skip-embedding
```

## 8. Test With Embedding

Use an already downloaded raw snapshot:

```bash
cd ~/sanction/pipeline

./server_run_all_sources_update.sh \
  --skip-download \
  --input-dir ~/sanction/pipeline/all_sources_raw_snapshots/<batch-name> \
  --batch-name all_sources_load_with_embedding_test
```

This performs:

```text
canonical CSV generation
-> validation
-> append-only DB insert
-> vector table setup
-> name/address embedding upsert
```

To tune embedding:

```bash
EMBEDDING_BATCH_SIZE=64 \
EMBEDDING_LOCAL_FILES_ONLY=true \
./server_run_all_sources_update.sh \
  --skip-download \
  --input-dir ~/sanction/pipeline/all_sources_raw_snapshots/<batch-name> \
  --batch-name all_sources_embedding_test
```

## 9. Post-Embedding Checks

```bash
docker exec -it sanction-postgres psql -U dslab -d sanction -c "
SELECT 'subject_name_embeddings' AS table_name, COUNT(*) FROM subject_name_embeddings
UNION ALL
SELECT 'subject_address_embeddings', COUNT(*) FROM subject_address_embeddings;
"
```

Check sample rows:

```bash
docker exec -it sanction-postgres psql -U dslab -d sanction -c "
SELECT subject_id, field_name, left(normalized_text, 80) AS text_sample, model_name
FROM subject_name_embeddings
ORDER BY updated_at DESC
LIMIT 5;
"
```

## 10. Operating Notes

The current embedding implementation embeds the current batch CSV files.

Because the embedding table has unique constraints:

```text
subject_name_embeddings: (subject_name_id, field_name)
subject_address_embeddings: (address_id, field_name)
```

re-running the same batch updates existing embedding rows rather than creating duplicates.

The current implementation does not query only DB-missing embedding rows. It re-embeds the current batch CSVs and upserts them. This matches the existing embedding implementation while remaining idempotent at the DB level.
