# Sanctions Candidate Search API

invoice party 정보를 입력받아 sanctions DB에서 제재 대상 후보를 검색하는 FastAPI 서버

## Prerequisites

- Docker / Docker Compose
- Python 3.10+

```bash
python3 -m pip install -U pandas psycopg sentence-transformers tqdm
```

embedding에 사용하는 모델:
```text
sentence-transformers/all-mpnet-base-v2
normalize_embeddings=True
```

## 1. Clone

```bash
git clone https://github.com/DSLab-MJU/sanction_project.git
cd sanction_project
```

## 2. Configure Env

```bash
cp server/.env.example server/.env
```

`server/.env`:

```env
POSTGRES_USER=dslab
POSTGRES_PASSWORD=PASSWORD
POSTGRES_DB=sanction
POSTGRES_HOST=sanction-postgres
POSTGRES_PORT=5432
```

## 3. Start Services

```bash
cd server
docker compose up --build -d
```

지금 단계까지는 DB schema/data/embedding이 아직 없으므로 `/search`는 데이터 로드 후 정상 동작합니다.

## 4. Create Base Schema

새 DB volume에서 1회만 실행:
```bash
cd ..
docker cp pipeline/schema_pg.sql sanction-postgres:/tmp/schema_pg.sql
docker exec -i sanction-postgres psql -U dslab -d sanction -f /tmp/schema_pg.sql
```

## 5. Load Sanctions Data + Embeddings

OFAC/UK/UN/EU source를 다운로드하고, 16개 schema CSV 생성, 검증, append-only DB load, pgvector embedding 생성을 수행

```bash
cd pipeline
PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:jeongho@mju.ac.kr)' \
SANCTION_DOCKER_CONTAINER=sanction-postgres \
SANCTION_DB_USER=dslab \
SANCTION_DB_NAME=sanction \
PGHOST=localhost \
PGPORT=5432 \
PGDATABASE=sanction \
PGUSER=dslab \
PGPASSWORD='PASSWORD' \
./server_run_all_sources_update.sh --trigger manual
```

검증만 실행:

```bash
PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:admin@example.com)' \
./server_run_all_sources_update.sh --trigger manual --skip-load
```

이미 받은 raw snapshot으로 재실행:

```bash
./server_run_all_sources_update.sh \
  --skip-download \
  --input-dir ./all_sources_raw_snapshots/<batch-name> \
  --batch-name all_sources_reload_test
```

## 6. Test

Health:

```bash
curl http://localhost:8000/health
```

Search:

```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  --data-binary @../server_test/test_request1.json
```

## API Input

`POST /search`는 invoice JSON을 받습니다. `parties[]`에 파싱된 정보를 담아서 넘겨야 합니다.

```json
{
  "invoice_number": "0090880005",
  "invoice_date": "2026-02-11",
  "currency": "CAD",
  "total_amount": 1264.0,
  "parties": [
    {
      "role": "ISSUER",
      "name": "AEROCARIBBEAN AIRLINES",
      "address": "Havana, Cuba",
      "country": "Cuba",
      "registration_number": "",
      "tax_id": "",
      "account_number": "",
      "swift": "",
      "iban": "",
      "account_holder": "",
      "phone": "",
      "email": ""
    }
  ]
}
```

Role enum:

```text
ISSUER
BILL_TO
REMIT_TO
BANK_BENEFICIARY
OTHER
```

## Notes

- API 서버는 `SentenceTransformer(MODEL_NAME)`로 모델을 로드합니다. 모델이 없으면 최초 실행 시 다운로드를 시도합니다.
- pipeline embedding도 기본값으로 모델 자동 다운로드를 허용합니다.
- `load_batch_append_only.sql`은 기존 row를 update/delete하지 않고 없는 primary key만 insert합니다.
