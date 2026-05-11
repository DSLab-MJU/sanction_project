# Server Pipeline Runbook

서버에서 입력 데이터만 받아 `통합 -> 검증 -> DB 적재`까지 실행하는 최소 파일 구성:

- `integrate_sanctions_pipeline.py`
- `ofac_remark_prefix_mapper.py`
- `validate_integrated_batch.py`
- `load_batch.sql`
- `load_batch_append_only.sql`
- `server_run_pipeline.sh`
- `server_run_ofac_update.sh`
- `server_run_all_sources_update.sh`

## 1. 서버로 파이프라인 코드 복사

로컬에서:

```bash
scp integrate_sanctions_pipeline.py \
    ofac_remark_prefix_mapper.py \
    validate_integrated_batch.py \
    load_batch.sql \
    load_batch_append_only.sql \
    server_run_pipeline.sh \
    server_run_ofac_update.sh \
    server_run_all_sources_update.sh \
    dslab@classnet:~/sanction/pipeline/
```

서버에서:

```bash
ssh dslab@classnet
mkdir -p ~/sanction/pipeline
chmod +x ~/sanction/pipeline/server_run_pipeline.sh
chmod +x ~/sanction/pipeline/server_run_ofac_update.sh
chmod +x ~/sanction/pipeline/server_run_all_sources_update.sh
```

## 2. 입력 파일 배치

예시:

```text
~/sanction/input_20260422/
  EU_20260410-FULL-1_1.csv
  UK-Sanctions-List.csv
  UN_consolidatedLegacyByPRN.xml
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

## 3. 검증만 실행

```bash
cd ~/sanction/pipeline
./server_run_pipeline.sh --input-dir ~/sanction/input_20260422 --skip-load
```

## 4. 검증 후 DB 적재까지 실행

`sanction_subjects`가 비어 있어야 한다. 비어 있지 않으면 스크립트가 중단된다.

```bash
cd ~/sanction/pipeline
./server_run_pipeline.sh --input-dir ~/sanction/input_20260422 --batch-name sanctions_20260422
```

## 5. 산출물 위치

```text
~/sanction/pipeline/server_runs/<batch-name>/
```

이 디렉터리에 16개 스키마 CSV와 검증용 메타 파일이 생성된다.

## 6. OFAC 자동 업데이트

OFAC만 주기적으로 갱신할 때는 `server_run_ofac_update.sh`를 사용한다.
이 스크립트는 OFAC SLS 페이지에서 SDN/Consolidated CSV 링크를 발견한 뒤 다운로드하고,
`integrate_sanctions_pipeline.py --skip-eu --skip-un --skip-uk`로 OFAC canonical CSV만 생성한다.

검증만 실행:

```bash
cd ~/sanction/pipeline
./server_run_ofac_update.sh --trigger manual --skip-load
```

다운로드를 생략하고 이미 받은 파일로 검증:

```bash
cd ~/sanction/pipeline
./server_run_ofac_update.sh --skip-download --input-dir ~/sanction/input_ofac --skip-load
```

검증 후 DB append-only 적재까지 실행:

```bash
cd ~/sanction/pipeline
OFAC_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' \
./server_run_ofac_update.sh --trigger manual
```

현재 OFAC loader는 `load_batch_append_only.sql`을 사용한다.
CSV를 임시 staging table에 먼저 적재한 뒤, 각 본 테이블에 없는 primary key만 insert한다.
기존 row는 update/delete/inactivate하지 않는다.
따라서 이 방식은 최신 상태 동기화가 아니라 append-only 누적 적재다.

주 1회 cron 예시:

```cron
0 3 * * 1 cd /home/dslab/sanction/pipeline && OFAC_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' ./server_run_ofac_update.sh --trigger scheduled >> /home/dslab/sanction/pipeline/ofac_update.log 2>&1
```

수동 즉시 실행은 같은 명령에서 `--trigger manual`만 사용하면 된다.

## 7. OFAC + UK + UN + EU 전체 자동 업데이트

전체 source를 주기적으로 갱신할 때는 `server_run_all_sources_update.sh`를 사용한다.
이 스크립트는 다음 공식 페이지/엔드포인트에서 최신 파일을 내려받는다.

```text
OFAC: https://sanctionslist.ofac.treas.gov/Home/static/index.html
UK:   https://www.gov.uk/government/publications/the-uk-sanctions-list
UN:   https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
EU:   https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions?locale=en
```

UN 안내 페이지가 서버 요청에 403을 반환하면 스크립트는 공식 XML 엔드포인트를 사용한다.

```text
https://scsanctions.un.org/resources/xml/en/consolidated.xml
```

검증만 실행:

```bash
cd ~/sanction/pipeline
PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' \
./server_run_all_sources_update.sh --trigger manual --skip-load
```

검증 후 DB append-only 적재까지 실행:

```bash
cd ~/sanction/pipeline
PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' \
./server_run_all_sources_update.sh --trigger manual
```

이미 받은 raw snapshot으로 재실행:

```bash
cd ~/sanction/pipeline
./server_run_all_sources_update.sh \
  --skip-download \
  --input-dir ~/sanction/pipeline/all_sources_raw_snapshots/<batch-name> \
  --batch-name all_sources_reload_test
```

주 1회 cron 예시:

```cron
0 4 * * 1 cd /home/dslab/sanction/pipeline && PIPELINE_USER_AGENT='SanctionPipeline/1.0 (+mailto:your-admin@example.com)' ./server_run_all_sources_update.sh --trigger scheduled >> /home/dslab/sanction/pipeline/all_sources_update.log 2>&1
```
