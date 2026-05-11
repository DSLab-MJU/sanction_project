import os
import re
from typing import Iterable, List, Tuple

import pandas as pd
import psycopg
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

BASE_DIR = os.path.expanduser(
    os.getenv("BASE_DIR") or os.getenv("BATCH_DIR") or "~/sanction/integrated_schema_batch_deploy"
)
MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-mpnet-base-v2")
BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "128"))
LOCAL_FILES_ONLY = os.getenv("EMBEDDING_LOCAL_FILES_ONLY", "false").lower() in {"1", "true", "yes", "y"}

DB_HOST = os.getenv("PGHOST", "localhost")
DB_PORT = os.getenv("PGPORT", "5432")
DB_NAME = os.getenv("PGDATABASE", "sanction")
DB_USER = os.getenv("PGUSER", "dslab")
DB_PASSWORD = os.getenv("PGPASSWORD", "")

SUBJECT_NAMES_CSV = os.path.join(BASE_DIR, "subject_names.csv")
SUBJECT_ADDRESSES_CSV = os.path.join(BASE_DIR, "subject_addresses.csv")


def normalize_text(text: str) -> str:
    text = str(text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def is_valid_text(x) -> bool:
    if x is None:
        return False
    if pd.isna(x):
        return False
    s = str(x).strip()
    return s != ""


def to_vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def load_subject_names():
    df = pd.read_csv(SUBJECT_NAMES_CSV, dtype=str).fillna("")
    rows = []

    for _, r in df.iterrows():
        subject_name_id = r["subject_name_id"].strip()
        subject_id = r["subject_id"].strip()

        full_name = r.get("full_name", "").strip()
        non_latin_name = r.get("non_latin_name", "").strip()

        if is_valid_text(full_name):
            rows.append((subject_name_id, subject_id, "full_name", full_name))

        if is_valid_text(non_latin_name):
            rows.append((subject_name_id, subject_id, "non_latin_name", non_latin_name))

    return rows


def load_subject_addresses():
    df = pd.read_csv(SUBJECT_ADDRESSES_CSV, dtype=str).fillna("")
    rows = []

    for _, r in df.iterrows():
        address_id = r["address_id"].strip()
        subject_id = r["subject_id"].strip()
        address_full_raw = r.get("address_full_raw", "").strip()

        if is_valid_text(address_full_raw):
            rows.append((address_id, subject_id, "address_full_raw", address_full_raw))

    return rows


UPSERT_NAME_SQL = """
INSERT INTO subject_name_embeddings
(subject_name_id, subject_id, field_name, raw_text, normalized_text, model_name, embedding, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s::vector, now())
ON CONFLICT (subject_name_id, field_name)
DO UPDATE SET
    raw_text = EXCLUDED.raw_text,
    normalized_text = EXCLUDED.normalized_text,
    model_name = EXCLUDED.model_name,
    embedding = EXCLUDED.embedding,
    updated_at = now();
"""

UPSERT_ADDRESS_SQL = """
INSERT INTO subject_address_embeddings
(address_id, subject_id, field_name, raw_text, normalized_text, model_name, embedding, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s::vector, now())
ON CONFLICT (address_id, field_name)
DO UPDATE SET
    raw_text = EXCLUDED.raw_text,
    normalized_text = EXCLUDED.normalized_text,
    model_name = EXCLUDED.model_name,
    embedding = EXCLUDED.embedding,
    updated_at = now();
"""


def embed_rows(model, rows):
    texts = [normalize_text(r[3]) for r in rows]
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    out = []
    for meta, emb in zip(rows, embeddings):
        raw_text = meta[3]
        normalized_text = normalize_text(raw_text)
        vector_literal = to_vector_literal(emb.tolist())
        out.append((*meta[:3], raw_text, normalized_text, MODEL_NAME, vector_literal))
    return out


def upsert_many(conn, sql, payloads, label):
    with conn.cursor() as cur:
        for batch in tqdm(list(chunked(payloads, 1000)), desc=f"DB upsert: {label}"):
            cur.executemany(sql, batch)
    conn.commit()


def main():
    print("[1/5] Loading model...")
    print(f"BASE_DIR   : {BASE_DIR}")
    print(f"MODEL_NAME : {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME, local_files_only=LOCAL_FILES_ONLY)

    print("[2/5] Reading CSV files...")
    name_rows = load_subject_names()
    address_rows = load_subject_addresses()

    print(f"subject_names target rows     : {len(name_rows):,}")
    print(f"subject_addresses target rows : {len(address_rows):,}")

    print("[3/5] Embedding subject_names...")
    name_payloads = embed_rows(model, name_rows) if name_rows else []

    print("[4/5] Embedding subject_addresses...")
    address_payloads = embed_rows(model, address_rows) if address_rows else []

    print("[5/5] Writing to PostgreSQL...")
    conn = psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )

    try:
        if name_payloads:
            upsert_many(conn, UPSERT_NAME_SQL, name_payloads, "subject_name_embeddings")
        if address_payloads:
            upsert_many(conn, UPSERT_ADDRESS_SQL, address_payloads, "subject_address_embeddings")
    finally:
        conn.close()

    print("Done.")


if __name__ == "__main__":
    main()
