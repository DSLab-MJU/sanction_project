#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./server_run_all_sources_update.sh [--trigger manual|scheduled] [--batch-name name] [--skip-load] [--skip-embedding]
  ./server_run_all_sources_update.sh --skip-download --input-dir /path/to/input [--skip-load] [--skip-embedding]

Purpose:
  Download current OFAC, UK, UN, and EU sanctions source files, build the
  canonical 16-table schema CSV batch, validate it, and optionally append only
  rows that are not already in the Postgres Docker container.

Default policy:
  - Existing rows are never updated, deleted, or inactivated
  - Database load is append-only: existing primary keys are skipped
  - Raw downloaded snapshots and generated schema CSV batches are preserved

Expected --skip-download input layout:
  <input-dir>/
    EU_*.csv
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

Environment overrides:
  PIPELINE_USER_AGENT         default: SanctionPipeline/1.0 (+mailto:admin@example.com)
  OFAC_SLS_URL                default: https://sanctionslist.ofac.treas.gov/Home/static/index.html
  UK_SOURCE_URL               default: https://www.gov.uk/government/publications/the-uk-sanctions-list
  UN_SOURCE_URL               default: https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
  UN_DOWNLOAD_URL             default: https://scsanctions.un.org/resources/xml/en/consolidated.xml
  EU_SOURCE_URL               default: https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions?locale=en
  EU_DOWNLOAD_URL             default: https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw
  SANCTION_DOCKER_CONTAINER   default: sanction-postgres
  SANCTION_DB_USER            default: dslab
  SANCTION_DB_NAME            default: sanction
  EMBEDDING_PGHOST            default: localhost
  EMBEDDING_PGPORT            default: 5432
  EMBEDDING_MODEL_NAME        default: sentence-transformers/all-mpnet-base-v2
  EMBEDDING_BATCH_SIZE        default: 128
  EMBEDDING_LOCAL_FILES_ONLY  default: true
EOF
}

log() {
  printf '[all-sources-update] %s\n' "$*"
}

fail() {
  printf '[all-sources-update] ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "missing file: $path"
}

find_one() {
  local base="$1"
  local pattern="$2"
  local found
  found="$(find "$base" -maxdepth 1 -type f -name "$pattern" | sort | head -n 1 || true)"
  [[ -n "$found" ]] || fail "could not find pattern '$pattern' in $base"
  printf '%s\n' "$found"
}

find_optional() {
  local base="$1"
  local pattern="$2"
  find "$base" -maxdepth 1 -type f -name "$pattern" | sort | head -n 1 || true
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TRIGGER="manual"
INPUT_DIR=""
OUTPUT_ROOT="$SCRIPT_DIR/all_sources_update_runs"
RAW_ROOT="$SCRIPT_DIR/all_sources_raw_snapshots"
BATCH_NAME=""
SKIP_DOWNLOAD=0
SKIP_LOAD=0
SKIP_EMBEDDING=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --trigger)
      TRIGGER="${2:-}"
      shift 2
      ;;
    --input-dir)
      INPUT_DIR="${2:-}"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="${2:-}"
      shift 2
      ;;
    --raw-root)
      RAW_ROOT="${2:-}"
      shift 2
      ;;
    --batch-name)
      BATCH_NAME="${2:-}"
      shift 2
      ;;
    --skip-download)
      SKIP_DOWNLOAD=1
      shift
      ;;
    --skip-load|--dry-run)
      SKIP_LOAD=1
      shift
      ;;
    --skip-embedding)
      SKIP_EMBEDDING=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

case "$TRIGGER" in
  manual|scheduled) ;;
  *) fail "--trigger must be manual or scheduled" ;;
esac

for file in \
  "$SCRIPT_DIR/integrate_sanctions_pipeline.py" \
  "$SCRIPT_DIR/ofac_remark_prefix_mapper.py" \
  "$SCRIPT_DIR/validate_integrated_batch.py" \
  "$SCRIPT_DIR/load_batch_append_only.sql"
do
  require_file "$file"
done

if [[ -z "$BATCH_NAME" ]]; then
  BATCH_NAME="sanctions_${TRIGGER}_$(date +%Y%m%d_%H%M%S)"
fi

mkdir -p "$OUTPUT_ROOT" "$RAW_ROOT"
OUTPUT_DIR="$OUTPUT_ROOT/$BATCH_NAME"
RAW_BATCH_DIR="$RAW_ROOT/$BATCH_NAME"

if [[ "$SKIP_DOWNLOAD" -eq 1 ]]; then
  [[ -n "$INPUT_DIR" ]] || fail "--input-dir is required with --skip-download"
  [[ -d "$INPUT_DIR" ]] || fail "input directory not found: $INPUT_DIR"
  EU_FILE="$(find_optional "$INPUT_DIR" 'EU*.csv')"
  UK_FILE="$(find_optional "$INPUT_DIR" 'UK-Sanctions-List.csv')"
  UN_FILE="$(find_optional "$INPUT_DIR" 'UN_consolidatedLegacyByPRN.xml')"
  OFAC_DIR="$INPUT_DIR/ofac"
else
  mkdir -p "$RAW_BATCH_DIR"
  log "discovering and downloading OFAC/UK/UN/EU files"
  PIPELINE_USER_AGENT="${PIPELINE_USER_AGENT:-SanctionPipeline/1.0 (+mailto:admin@example.com)}"
  OFAC_SLS_URL="${OFAC_SLS_URL:-https://sanctionslist.ofac.treas.gov/Home/static/index.html}"
  UK_SOURCE_URL="${UK_SOURCE_URL:-https://www.gov.uk/government/publications/the-uk-sanctions-list}"
  UN_SOURCE_URL="${UN_SOURCE_URL:-https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list}"
  UN_DOWNLOAD_URL="${UN_DOWNLOAD_URL:-https://scsanctions.un.org/resources/xml/en/consolidated.xml}"
  EU_SOURCE_URL="${EU_SOURCE_URL:-https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions?locale=en}"
  EU_DOWNLOAD_URL="${EU_DOWNLOAD_URL:-https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw}"
  PIPELINE_USER_AGENT="$PIPELINE_USER_AGENT" \
  OFAC_SLS_URL="$OFAC_SLS_URL" \
  UK_SOURCE_URL="$UK_SOURCE_URL" \
  UN_SOURCE_URL="$UN_SOURCE_URL" \
  UN_DOWNLOAD_URL="$UN_DOWNLOAD_URL" \
  EU_SOURCE_URL="$EU_SOURCE_URL" \
  EU_DOWNLOAD_URL="$EU_DOWNLOAD_URL" \
  RAW_BATCH_DIR="$RAW_BATCH_DIR" \
  python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = os.environ["PIPELINE_USER_AGENT"]
RAW_BATCH_DIR = Path(os.environ["RAW_BATCH_DIR"])
DISCOVERY_DIR = RAW_BATCH_DIR / "discovery"
OFAC_DIR = RAW_BATCH_DIR / "ofac"
DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
OFAC_DIR.mkdir(parents=True, exist_ok=True)

URL_RE = re.compile(r"""(?i)(?:href|src)=["']([^"']+)["']|https?://[^\s"'<>]+""")
OFAC_REQUIRED = {
    "SDN.CSV": OFAC_DIR / "sdn.csv",
    "SDN_COMMENTS.CSV": OFAC_DIR / "sdn_comments.csv",
    "ALT.CSV": OFAC_DIR / "alt.csv",
    "ADD.CSV": OFAC_DIR / "add.csv",
    "CONS_PRIM.CSV": OFAC_DIR / "cons_prim.csv",
    "CONS_COMMENTS.CSV": OFAC_DIR / "cons_comments.csv",
    "CONS_ALT.CSV": OFAC_DIR / "cons_alt.csv",
    "CONS_ADD.CSV": OFAC_DIR / "cons_add.csv",
}


@dataclass
class FetchResult:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes


def fetch(url: str, *, retries: int = 3, timeout: int = 60) -> FetchResult:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout) as response:
                return FetchResult(
                    url=response.geturl(),
                    status=getattr(response, "status", 200),
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=response.read(),
                )
        except Exception as exc:  # noqa: BLE001 - surfaced after retries
            last_error = exc
            if attempt < retries:
                time.sleep(attempt * 2)
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last_error}")


def text_from(result: FetchResult) -> str:
    return result.body.decode("utf-8", errors="replace")


def extract_links(base_url: str, text: str) -> list[str]:
    links: list[str] = []
    for match in URL_RE.finditer(text):
        raw = match.group(1) or match.group(0)
        raw = raw.strip().rstrip("),.;")
        if not raw or raw.startswith(("data:", "mailto:", "javascript:")):
            continue
        links.append(urljoin(base_url, raw))
    return links


def same_origin(url: str, other: str) -> bool:
    left = urlparse(url)
    right = urlparse(other)
    return (left.scheme, left.netloc) == (right.scheme, right.netloc)


def candidate_assets(base_url: str, links: Iterable[str]) -> list[str]:
    assets: list[str] = []
    seen: set[str] = set()
    for link in links:
        if not same_origin(base_url, link):
            continue
        path = urlparse(link).path.lower()
        if path.endswith((".js", ".json", ".html", ".htm")) and link not in seen:
            assets.append(link)
            seen.add(link)
    return assets[:100]


def page_text_blobs(source_name: str, url: str) -> list[tuple[str, str]]:
    page = fetch(url)
    page_text = text_from(page)
    (DISCOVERY_DIR / f"{source_name}_page.html").write_text(page_text, encoding="utf-8")
    blobs: list[tuple[str, str]] = [(page.url, page_text)]
    for idx, asset_url in enumerate(candidate_assets(page.url, extract_links(page.url, page_text)), start=1):
        try:
            asset = fetch(asset_url, retries=2, timeout=30)
        except Exception:
            continue
        asset_text = text_from(asset)
        suffix = Path(urlparse(asset.url).path).suffix or ".txt"
        (DISCOVERY_DIR / f"{source_name}_asset_{idx:03d}{suffix}").write_text(asset_text, encoding="utf-8")
        blobs.append((asset.url, asset_text))
    return blobs


def find_link(blobs: Iterable[tuple[str, str]], predicates: Iterable[callable]) -> str | None:
    for base_url, text in blobs:
        for link in extract_links(base_url, text):
            decoded = unquote(link)
            lowered = decoded.lower()
            if any(predicate(decoded, lowered) for predicate in predicates):
                return link
    return None


manifest: list[dict[str, str]] = []


def save_download(dataset: str, source_page_url: str, download_url: str, output_path: Path) -> None:
    result = fetch(download_url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(result.body)
    manifest.append(
        {
            "dataset": dataset,
            "source_page_url": source_page_url,
            "download_url": download_url,
            "final_url": result.url,
            "local_path": str(output_path.relative_to(RAW_BATCH_DIR)),
            "http_status": str(result.status),
            "content_length": str(len(result.body)),
            "sha256_hash": hashlib.sha256(result.body).hexdigest(),
        }
    )


def download_ofac() -> None:
    source_url = os.environ["OFAC_SLS_URL"]
    blobs = page_text_blobs("ofac", source_url)
    found: dict[str, str] = {}
    for base_url, text in blobs:
        for link in extract_links(base_url, text):
            decoded = unquote(link).upper()
            for required_name in OFAC_REQUIRED:
                if required_name in decoded and required_name not in found:
                    found[required_name] = link
    missing = [name for name in OFAC_REQUIRED if name not in found]
    if missing:
        raise RuntimeError("OFAC discovery failed. Missing required files: " + ", ".join(missing))
    for source_name, output_path in OFAC_REQUIRED.items():
        save_download(f"OFAC_{source_name}", source_url, found[source_name], output_path)


def download_uk() -> None:
    source_url = os.environ["UK_SOURCE_URL"]
    blobs = page_text_blobs("uk", source_url)
    link = find_link(
        blobs,
        [
            lambda _decoded, lowered: "uk-sanctions-list.csv" in lowered,
            lambda _decoded, lowered: lowered.endswith(".csv") and "sanctions" in lowered and "uk" in lowered,
        ],
    )
    if not link:
        raise RuntimeError("UK discovery failed. Could not find UK-Sanctions-List.csv")
    save_download("UK-Sanctions-List.csv", source_url, link, RAW_BATCH_DIR / "UK-Sanctions-List.csv")


def download_un() -> None:
    source_url = os.environ["UN_SOURCE_URL"]
    fallback_url = os.environ["UN_DOWNLOAD_URL"]
    try:
        blobs = page_text_blobs("un", source_url)
        link = find_link(
            blobs,
            [
                lambda _decoded, lowered: "resources/xml/en/consolidated.xml" in lowered,
                lambda _decoded, lowered: lowered.endswith(".xml") and "consolidated" in lowered and "scsanctions" in lowered,
            ],
        )
    except Exception:
        link = None
    if not link:
        link = fallback_url
    save_download("UN_consolidatedLegacyByPRN.xml", source_url, link, RAW_BATCH_DIR / "UN_consolidatedLegacyByPRN.xml")


def download_eu() -> None:
    source_url = os.environ["EU_SOURCE_URL"]
    fallback_url = os.environ["EU_DOWNLOAD_URL"]
    try:
        blobs = page_text_blobs("eu", source_url)
        link = find_link(
            blobs,
            [
                lambda _decoded, lowered: "csvfullsanctionslist_1_1" in lowered,
                lambda _decoded, lowered: lowered.endswith(".csv") and "sanction" in lowered,
            ],
        )
    except Exception:
        link = None
    if not link:
        link = fallback_url
    save_download("EU_consolidated_1_1.csv", source_url, link, RAW_BATCH_DIR / "EU_consolidated_1_1.csv")


errors: list[dict[str, str]] = []


def run_source(source_name: str, fn) -> None:
    try:
        fn()
        print(f"source_download_ok={source_name}")
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": source_name, "error": str(exc)})
        print(f"source_download_skipped={source_name} error={exc}", file=sys.stderr)


run_source("OFAC", download_ofac)
run_source("UK", download_uk)
run_source("UN", download_un)
run_source("EU", download_eu)

if errors:
    (RAW_BATCH_DIR / "download_errors.json").write_text(json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8")
    with (RAW_BATCH_DIR / "download_errors.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "error"])
        writer.writeheader()
        writer.writerows(errors)

if not manifest:
    print("all source downloads failed; nothing to parse", file=sys.stderr)
    print(f"discovery_dir={DISCOVERY_DIR}", file=sys.stderr)
    sys.exit(2)

(RAW_BATCH_DIR / "download_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
with (RAW_BATCH_DIR / "download_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(manifest[0]))
    writer.writeheader()
    writer.writerows(manifest)

print(f"downloaded_files={len(manifest)}")
print(f"skipped_sources={len(errors)}")
print(f"raw_dir={RAW_BATCH_DIR}")
PY
  EU_FILE="$RAW_BATCH_DIR/EU_consolidated_1_1.csv"
  UK_FILE="$RAW_BATCH_DIR/UK-Sanctions-List.csv"
  UN_FILE="$RAW_BATCH_DIR/UN_consolidatedLegacyByPRN.xml"
  OFAC_DIR="$RAW_BATCH_DIR/ofac"
fi

SKIP_OFAC_SOURCE=0
SKIP_EU_SOURCE=0
SKIP_UN_SOURCE=0
SKIP_UK_SOURCE=0

OFAC_REQUIRED_FILES=(
  "$OFAC_DIR/sdn.csv"
  "$OFAC_DIR/sdn_comments.csv"
  "$OFAC_DIR/alt.csv"
  "$OFAC_DIR/add.csv"
  "$OFAC_DIR/cons_prim.csv"
  "$OFAC_DIR/cons_comments.csv"
  "$OFAC_DIR/cons_alt.csv"
  "$OFAC_DIR/cons_add.csv"
)

if [[ ! -d "$OFAC_DIR" ]]; then
  SKIP_OFAC_SOURCE=1
else
  for file in "${OFAC_REQUIRED_FILES[@]}"; do
    if [[ ! -f "$file" ]]; then
      SKIP_OFAC_SOURCE=1
      break
    fi
  done
fi

if [[ "$SKIP_OFAC_SOURCE" -eq 1 ]]; then
  log "skipping OFAC: required OFAC files are incomplete"
fi
if [[ -z "${EU_FILE:-}" || ! -f "$EU_FILE" ]]; then
  SKIP_EU_SOURCE=1
  log "skipping EU: source file is unavailable"
fi
if [[ -z "${UN_FILE:-}" || ! -f "$UN_FILE" ]]; then
  SKIP_UN_SOURCE=1
  log "skipping UN: source file is unavailable"
fi
if [[ -z "${UK_FILE:-}" || ! -f "$UK_FILE" ]]; then
  SKIP_UK_SOURCE=1
  log "skipping UK: source file is unavailable"
fi

if [[ "$SKIP_OFAC_SOURCE" -eq 1 && "$SKIP_EU_SOURCE" -eq 1 && "$SKIP_UN_SOURCE" -eq 1 && "$SKIP_UK_SOURCE" -eq 1 ]]; then
  fail "no source files are available after download/discovery; aborting"
fi

PARSER_ARGS=(
  --output-dir "$OUTPUT_DIR"
)
if [[ "$SKIP_OFAC_SOURCE" -eq 1 ]]; then
  PARSER_ARGS+=(--skip-ofac)
else
  PARSER_ARGS+=(--ofac-dir "$OFAC_DIR")
fi
if [[ "$SKIP_EU_SOURCE" -eq 1 ]]; then
  PARSER_ARGS+=(--skip-eu)
else
  PARSER_ARGS+=(--eu "$EU_FILE")
fi
if [[ "$SKIP_UN_SOURCE" -eq 1 ]]; then
  PARSER_ARGS+=(--skip-un)
else
  PARSER_ARGS+=(--un "$UN_FILE")
fi
if [[ "$SKIP_UK_SOURCE" -eq 1 ]]; then
  PARSER_ARGS+=(--skip-uk)
else
  PARSER_ARGS+=(--uk "$UK_FILE")
fi

log "building canonical all-sources batch"
python3 "$SCRIPT_DIR/integrate_sanctions_pipeline.py" "${PARSER_ARGS[@]}"

log "validating canonical batch"
python3 "$SCRIPT_DIR/validate_integrated_batch.py" "$OUTPUT_DIR"

if [[ "$SKIP_LOAD" -eq 1 ]]; then
  log "validation passed; skipping database load"
  log "output_dir=$OUTPUT_DIR"
  exit 0
fi

CONTAINER="${SANCTION_DOCKER_CONTAINER:-sanction-postgres}"
DB_USER="${SANCTION_DB_USER:-dslab}"
DB_NAME="${SANCTION_DB_NAME:-sanction}"

log "copying batch into container"
docker cp "$OUTPUT_DIR" "$CONTAINER:/tmp/"
docker cp "$SCRIPT_DIR/load_batch_append_only.sql" "$CONTAINER:/tmp/load_batch_append_only.sql"

log "append-only loading batch into database"
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v batch_dir="/tmp/$BATCH_NAME" -f /tmp/load_batch_append_only.sql

log "append-only load finished"

if [[ "$SKIP_EMBEDDING" -eq 1 ]]; then
  log "skipping embedding load"
  exit 0
fi

EMBEDDING_SCRIPT="$SCRIPT_DIR/embedding/load_pgvector_embeddings.py"
VECTOR_SETTING_SQL="$SCRIPT_DIR/embedding/vector_setting.sql"
require_file "$EMBEDDING_SCRIPT"
require_file "$VECTOR_SETTING_SQL"

log "ensuring pgvector embedding tables exist"
docker cp "$VECTOR_SETTING_SQL" "$CONTAINER:/tmp/vector_setting.sql"
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -f /tmp/vector_setting.sql

log "embedding current batch names and addresses into pgvector"
BASE_DIR="$OUTPUT_DIR" \
PGHOST="${EMBEDDING_PGHOST:-${PGHOST:-localhost}}" \
PGPORT="${EMBEDDING_PGPORT:-${PGPORT:-5432}}" \
PGDATABASE="${PGDATABASE:-$DB_NAME}" \
PGUSER="${PGUSER:-$DB_USER}" \
PGPASSWORD="${PGPASSWORD:-}" \
EMBEDDING_MODEL_NAME="${EMBEDDING_MODEL_NAME:-sentence-transformers/all-mpnet-base-v2}" \
EMBEDDING_BATCH_SIZE="${EMBEDDING_BATCH_SIZE:-128}" \
EMBEDDING_LOCAL_FILES_ONLY="${EMBEDDING_LOCAL_FILES_ONLY:-true}" \
python3 "$EMBEDDING_SCRIPT"

log "embedding load finished"
