#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from ofac_remark_prefix_mapper import TABLES


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\+\d{2}:\d{2}|Z)?$")
NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")

PK_COLUMNS = {
    "sanction_subjects": "subject_id",
    "subject_names": "subject_name_id",
    "subject_addresses": "address_id",
    "subject_identifiers": "identifier_id",
    "subject_birth_dates": "birth_date_id",
    "subject_birth_places": "birth_place_id",
    "subject_nationalities": "nationality_id",
    "subject_contacts": "contact_id",
    "subject_relationships": "relationship_id",
    "subject_vessel_details": "vessel_detail_id",
    "subject_programs": "program_id",
    "subject_regulations": "regulation_id",
    "subject_measures": "measure_id",
    "subject_notes": "note_id",
    "subject_source_records": "source_record_id",
    "subject_update_events": "update_id",
}

REQUIRED_COLUMNS = {
    "sanction_subjects": ["subject_id", "source_system", "source_dataset", "subject_type", "primary_name", "is_active"],
    "subject_names": ["subject_name_id", "subject_id", "full_name", "name_type", "is_primary"],
    "subject_addresses": ["address_id", "subject_id"],
    "subject_identifiers": ["identifier_id", "subject_id", "identifier_type", "identifier_value"],
    "subject_birth_dates": ["birth_date_id", "subject_id"],
    "subject_birth_places": ["birth_place_id", "subject_id"],
    "subject_nationalities": ["nationality_id", "subject_id"],
    "subject_contacts": ["contact_id", "subject_id", "contact_type", "contact_value"],
    "subject_relationships": ["relationship_id", "subject_id", "relationship_type", "related_name"],
    "subject_vessel_details": ["vessel_detail_id", "subject_id"],
    "subject_programs": ["program_id", "subject_id", "list_family"],
    "subject_regulations": ["regulation_id", "subject_id"],
    "subject_measures": ["measure_id", "subject_id"],
    "subject_notes": ["note_id", "subject_id", "note_type", "note_text"],
    "subject_source_records": ["source_record_id", "subject_id", "source_system", "source_dataset", "source_primary_id", "source_component_type", "source_component_id"],
    "subject_update_events": ["update_id", "subject_id"],
}

ENUMS = {
    ("sanction_subjects", "subject_type"): {"INDIVIDUAL", "ENTITY", "GROUP", "VESSEL", "AIRCRAFT"},
    ("subject_contacts", "contact_type"): {"PHONE", "EMAIL", "WEBSITE"},
    ("subject_names", "name_type"): {"PRIMARY", "ALIAS", "AKA", "FKA", "NKA", "TRANSLITERATION"},
}

DATE_COLUMNS = {
    ("sanction_subjects", "designation_date"),
    ("subject_identifiers", "issued_date"),
    ("subject_identifiers", "valid_from"),
    ("subject_identifiers", "valid_to"),
    ("subject_birth_dates", "birth_date"),
    ("subject_regulations", "publication_date"),
    ("subject_regulations", "entry_into_force_date"),
    ("subject_update_events", "update_date"),
}

NUMERIC_COLUMNS = {
    ("subject_vessel_details", "tonnage"),
    ("subject_vessel_details", "grt"),
    ("subject_vessel_details", "length"),
    ("subject_vessel_details", "year_built"),
}

TIMESTAMP_COLUMNS = {
    ("sanction_subjects", "created_at"),
    ("sanction_subjects", "updated_at"),
}
for table, columns in TABLES.items():
    for column in columns:
        if column == "created_at" and table != "sanction_subjects":
            TIMESTAMP_COLUMNS.add((table, column))


def semantic_key_fn(table: str) -> Callable[[dict[str, str]], tuple]:
    mapping = {
        "subject_names": lambda r: (r["subject_id"], r["full_name"].strip() or r["non_latin_name"].strip(), r["name_type"]),
        "subject_addresses": lambda r: (r["subject_id"], r["address_full_raw"].strip(), r["country_name"].strip()),
        "subject_identifiers": lambda r: (r["subject_id"], r["identifier_type"], r["identifier_value"].strip()),
        "subject_birth_dates": lambda r: (r["subject_id"], r["birth_date"], r["year"], r["year_from"], r["year_to"], r["date_type_raw"]),
        "subject_birth_places": lambda r: (r["subject_id"], r["place"].strip(), r["city"].strip(), r["country_name"].strip()),
        "subject_nationalities": lambda r: (r["subject_id"], r["country_code"].strip(), r["country_name"].strip(), r["nationality_raw"].strip()),
        "subject_contacts": lambda r: (r["subject_id"], r["contact_type"], r["contact_value"].strip()),
        "subject_relationships": lambda r: (r["subject_id"], r["relationship_type"], r["related_name"].strip()),
        "subject_vessel_details": lambda r: (r["subject_id"], r["imo_number"].strip(), r["call_sign"].strip(), r["vessel_type"].strip(), r["flag_current"].strip()),
        "subject_programs": lambda r: (r["subject_id"], r["list_family"], r["regime_name"].strip(), r["program_name"].strip(), r["source_component_scope"]),
        "subject_regulations": lambda r: (r["subject_id"], r["regulation_scope"], r["regulation_type"].strip(), r["organisation_type"].strip(), r["publication_date"], r["entry_into_force_date"], r["number_title"].strip(), r["publication_url"].strip(), r["regulation_language"].strip()),
        "subject_measures": lambda r: (r["subject_id"], r["measure_type"], r["measure_raw_text"].strip()),
        "subject_notes": lambda r: (r["subject_id"], r["note_type"], r["note_text"].strip()),
    }
    return mapping[table]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate integrated sanctions CSV batch before DB load.")
    parser.add_argument("batch_dir", type=Path)
    args = parser.parse_args()

    batch_dir = args.batch_dir
    errors: list[str] = []
    warnings: list[str] = []
    loaded: dict[str, list[dict[str, str]]] = {}

    for table, columns in TABLES.items():
        path = batch_dir / f"{table}.csv"
        if not path.exists():
            errors.append(f"missing file: {path}")
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                errors.append(f"{table}: header mismatch")
                continue
            rows = list(reader)
            loaded[table] = rows

    if errors:
        print("VALIDATION_FAILED")
        for error in errors:
            print("ERROR", error)
        return 1

    subject_ids = {row["subject_id"] for row in loaded["sanction_subjects"]}

    for table, rows in loaded.items():
        pk_col = PK_COLUMNS[table]
        pk_counter = Counter(row[pk_col] for row in rows)
        for pk, count in pk_counter.items():
            if count > 1:
                errors.append(f"{table}: duplicate {pk_col}={pk} count={count}")
                break

        for col in REQUIRED_COLUMNS[table]:
            missing = sum(1 for row in rows if not row[col].strip())
            if missing:
                errors.append(f"{table}: missing required column {col} rows={missing}")

        if table != "sanction_subjects":
            dangling = sum(1 for row in rows if row["subject_id"] not in subject_ids)
            if dangling:
                errors.append(f"{table}: dangling subject_id rows={dangling}")

        for (enum_table, col), allowed in ENUMS.items():
            if enum_table != table:
                continue
            bad = sorted({row[col] for row in rows if row[col].strip() and row[col] not in allowed})
            if bad:
                errors.append(f"{table}: invalid {col} values={bad[:10]}")

        for row in rows:
            for value in row.values():
                if value == "-0-":
                    errors.append(f"{table}: unresolved null sentinel -0-")
                    break
            for (dt_table, col) in DATE_COLUMNS:
                if dt_table != table:
                    continue
                value = row[col].strip()
                if value and not DATE_RE.fullmatch(value):
                    errors.append(f"{table}: invalid date {col}={value}")
                    break
            for (ts_table, col) in TIMESTAMP_COLUMNS:
                if ts_table != table:
                    continue
                value = row[col].strip()
                if value and not TIMESTAMP_RE.fullmatch(value):
                    errors.append(f"{table}: invalid timestamp {col}={value}")
                    break
            for (num_table, col) in NUMERIC_COLUMNS:
                if num_table != table:
                    continue
                value = row[col].strip()
                if value and not NUMERIC_RE.fullmatch(value):
                    errors.append(f"{table}: invalid numeric {col}={value}")
                    break

    primary_counts = Counter(row["subject_id"] for row in loaded["subject_names"] if row["is_primary"] == "1")
    zero_primary = sum(1 for sid in subject_ids if primary_counts[sid] == 0)
    multi_primary = sum(1 for sid, count in primary_counts.items() if count > 1)
    if zero_primary:
        errors.append(f"subject_names: subjects with zero primary rows={zero_primary}")
    if multi_primary:
        errors.append(f"subject_names: subjects with multiple primary rows={multi_primary}")

    vessel_subject_counts = Counter(row["subject_id"] for row in loaded["subject_vessel_details"])
    multi_vessel_rows = sum(1 for _sid, count in vessel_subject_counts.items() if count > 1)
    if multi_vessel_rows:
        errors.append(f"subject_vessel_details: subjects with multiple rows={multi_vessel_rows}")

    for table in [
        "subject_names",
        "subject_addresses",
        "subject_identifiers",
        "subject_birth_dates",
        "subject_birth_places",
        "subject_nationalities",
        "subject_contacts",
        "subject_relationships",
        "subject_vessel_details",
        "subject_programs",
        "subject_regulations",
        "subject_measures",
        "subject_notes",
    ]:
        key_counter = Counter(semantic_key_fn(table)(row) for row in loaded[table])
        dup = sum(count - 1 for count in key_counter.values() if count > 1)
        if dup:
            errors.append(f"{table}: semantic duplicate rows={dup}")

    print("VALIDATION_SUMMARY")
    for table in TABLES:
        print(f"{table} rows={len(loaded[table])}")
    if warnings:
        for warning in warnings:
            print("WARNING", warning)
    if errors:
        print("VALIDATION_FAILED")
        for error in errors:
            print("ERROR", error)
        return 1
    print("VALIDATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
