#!/usr/bin/env python3
"""
Reusable staging pipeline that normalizes EU, UN, UK, and OFAC source files
into the common 16-table schema.

The pipeline is designed to be re-run for future DB updates:
  1. parse each upstream source
  2. normalize into table-level CSVs
  3. keep lineage/source IDs for later bulk insert

Current source inputs:
  - EU_20260410-FULL-1_1.csv
  - UN_consolidatedLegacyByPRN.xml
  - UK-Sanctions-List.csv
  - ofac/*.csv

OFAC note:
  - sdn_comments.csv is appended directly to sdn.csv remarks
  - cons_comments.csv is appended directly to cons_prim.csv remarks
  - the comment fragments are spillovers from the base remark column, so they
    are concatenated without adding separators
"""

from __future__ import annotations

import argparse
import csv
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Sequence, Tuple

from ofac_remark_prefix_mapper import (
    TABLES,
    Context,
    RULES,
    blank_row,
    clean,
    clean_trailing,
    normalize_subject_type,
    nullish,
    split_programs,
    split_remark_segments,
    stable_id,
)


ID_COLUMNS = {table: columns[0] for table, columns in TABLES.items() if columns}
IGNORE_DEDUPE_COLUMNS = {"created_at", "updated_at"}
DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
]
COUNTRY_HINTS = {
    "Afghanistan",
    "Algeria",
    "Argentina",
    "Belgium",
    "Belarus",
    "Bosnia and Herzegovina",
    "Brazil",
    "Burma",
    "China",
    "Colombia",
    "Congo",
    "Costa Rica",
    "Cuba",
    "Democratic Republic of the Congo",
    "Egypt",
    "France",
    "Germany",
    "Guatemala",
    "Guinea",
    "Hong Kong",
    "India",
    "Indonesia",
    "Iran",
    "Iraq",
    "Italy",
    "Japan",
    "Jordan",
    "Kenya",
    "Korea, North",
    "Lebanon",
    "Liberia",
    "Libya",
    "Mali",
    "Mexico",
    "Moldova",
    "Montenegro",
    "Morocco",
    "Mozambique",
    "Pakistan",
    "Palestinian",
    "Panama",
    "Peru",
    "Philippines",
    "Qatar",
    "Romania",
    "Russia",
    "Rwanda",
    "Saudi Arabia",
    "Senegal",
    "Seychelles",
    "Slovenia",
    "Somalia",
    "Spain",
    "Sudan",
    "Switzerland",
    "Syria",
    "Tanzania",
    "Thailand",
    "Turkey",
    "Uganda",
    "Ukraine",
    "United Arab Emirates",
    "United Kingdom",
    "United States",
    "Venezuela",
    "Vietnam",
    "Yemen",
}


def parse_date(value: str) -> str:
    value = clean_trailing(value)
    if not value:
        return ""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def parse_report_date(header_line: str) -> str:
    if ":" not in header_line:
        return ""
    return parse_date(header_line.split(":", 1)[1].strip())


def to_flag(value: str) -> str:
    lowered = clean(value).lower()
    if lowered in {"true", "1", "yes", "y"}:
        return "1"
    if lowered in {"false", "0", "no", "n"}:
        return "0"
    return ""


def split_multi(value: str, separators: Sequence[str] = (";",)) -> List[str]:
    text = clean(value)
    if not text or text == "-0-":
        return []
    parts = [text]
    for sep in separators:
        next_parts: List[str] = []
        for part in parts:
            next_parts.extend(piece.strip() for piece in part.split(sep))
        parts = next_parts
    return [part for part in parts if part and part != "-0-"]


def join_nonempty(values: Sequence[str], sep: str = ", ") -> str:
    return sep.join(clean(v) for v in values if clean(v) and clean(v) != "-0-")


def make_subject_uuid(source_system: str, source_dataset: str, source_primary_id: str) -> str:
    return stable_id("subject", source_system, source_dataset, source_primary_id)


def eu_subject_type(raw: str) -> str:
    lowered = clean(raw).lower()
    if lowered in {"p", "person"}:
        return "INDIVIDUAL"
    if lowered in {"e", "enterprise"}:
        return "ENTITY"
    if lowered == "group":
        return "GROUP"
    return "ENTITY"


def uk_subject_type(raw: str) -> str:
    lowered = clean(raw).lower()
    if lowered == "individual":
        return "INDIVIDUAL"
    if lowered == "entity":
        return "ENTITY"
    if lowered == "ship":
        return "VESSEL"
    return "ENTITY"


def uk_primary_name(row: Dict[str, str]) -> str:
    explicit = clean(row.get("Name 6", ""))
    if explicit:
        return explicit
    parts = [clean(row.get(f"Name {idx}", "")) for idx in range(1, 7)]
    return " ".join(part for part in parts if part)


def uk_name_type(raw: str, is_primary: bool) -> str:
    if is_primary:
        return "PRIMARY"
    lowered = clean(raw).lower()
    if "alias" in lowered:
        return "ALIAS"
    return "ALIAS"


def name_type_from_alt(raw: str) -> str:
    lowered = clean(raw).lower()
    if lowered == "aka":
        return "AKA"
    if lowered == "fka":
        return "FKA"
    if lowered == "nka":
        return "NKA"
    return "ALIAS"


def un_full_name(node: ET.Element) -> Tuple[str, List[str]]:
    parts = [
        clean(node.findtext("FIRST_NAME", "")),
        clean(node.findtext("SECOND_NAME", "")),
        clean(node.findtext("THIRD_NAME", "")),
        clean(node.findtext("FOURTH_NAME", "")),
    ]
    present = [part for part in parts if part]
    return " ".join(present), parts


def eu_name_fields(row: Dict[str, str]) -> Tuple[str, str, str, str]:
    last_name = clean(row.get("NameAlias_LastName", ""))
    first_name = clean(row.get("NameAlias_FirstName", ""))
    middle_name = clean(row.get("NameAlias_MiddleName", ""))
    whole_name = clean(row.get("NameAlias_WholeName", ""))
    if not whole_name:
        whole_name = " ".join(part for part in [first_name, middle_name, last_name] if part)
    return whole_name, last_name, first_name, middle_name


def parse_uk_birth_value(raw: str) -> Dict[str, str]:
    value = clean_trailing(raw)
    result = {
        "birth_date": "",
        "day": "",
        "month": "",
        "year": "",
        "year_from": "",
        "year_to": "",
        "circa_flag": "0",
        "calendar_type": "",
        "date_type_raw": "",
        "is_incomplete": "0",
    }
    exact = parse_date(value)
    if exact:
        year, month, day = exact.split("-")
        result.update({"birth_date": exact, "year": year, "month": str(int(month)), "day": str(int(day))})
        return result
    if value.isdigit() and len(value) == 4:
        result["year"] = value
        result["is_incomplete"] = "1"
        return result
    result["date_type_raw"] = value
    result["is_incomplete"] = "1"
    return result


def parse_un_identifier_type(raw: str) -> str:
    lowered = clean(raw).lower()
    if "passport" in lowered:
        return "PASSPORT"
    if "identification" in lowered or "identity" in lowered or "national" in lowered:
        return "NATIONAL_ID"
    return "OTHER"


def parse_eu_identifier_type(type_code: str, type_description: str) -> str:
    lowered = f"{clean(type_code)} {clean(type_description)}".lower()
    if "passport" in lowered:
        return "PASSPORT"
    if "imo" in lowered:
        return "IMO_NUMBER"
    if "tax" in lowered or "fiscal" in lowered:
        return "TAX_ID"
    if "registration" in lowered or "company" in lowered or "business" in lowered:
        return "BUSINESS_REGISTRATION"
    if "identity" in lowered or "identification" in lowered or "national" in lowered:
        return "NATIONAL_ID"
    return clean(type_code) or "OTHER"


def parse_place_text(value: str) -> Tuple[str, str, str]:
    place = clean_trailing(value)
    parts = [part.strip() for part in place.split(",") if part.strip()]
    if len(parts) >= 2 and parts[-1] in COUNTRY_HINTS:
        return place, parts[0], parts[-1]
    if len(parts) == 1 and parts[0] in COUNTRY_HINTS:
        return place, "", parts[0]
    return place, "", ""


@dataclass
class PipelineBuilder:
    created_at: str

    def __post_init__(self) -> None:
        self.ctx = Context(self.created_at)
        self.table_seen: Dict[str, set] = {table: set() for table in TABLES}
        self.subject_primary_names: set[str] = set()
        self.subjects_with_primary_name: set[str] = set()
        self.subject_source_records: set[Tuple[str, str, str]] = set()
        self.subject_source_record_rows: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        self.ofac_rule_counts: Counter[str] = Counter()
        self.unmapped_ofac_segments: List[Dict[str, str]] = []

    def add_row(self, table: str, row: Dict[str, str]) -> None:
        full = blank_row(table)
        full.update(row)
        if "created_at" in full and not full["created_at"]:
            full["created_at"] = self.created_at
        if "updated_at" in full and not full["updated_at"]:
            full["updated_at"] = self.created_at
        key = tuple(full[column] for column in TABLES[table] if column not in IGNORE_DEDUPE_COLUMNS)
        if key in self.table_seen[table]:
            return
        self.table_seen[table].add(key)
        self.ctx.add(table, full)

    def ensure_subject(
        self,
        source_system: str,
        source_dataset: str,
        source_primary_id: str,
        subject_type: str,
        subject_type_raw: str,
        primary_name: str,
        title: str = "",
        gender: str = "",
        function_role: str = "",
        designation_date: str = "",
        designation_details_raw: str = "",
        designation_source_raw: str = "",
        entity_subtype_raw: str = "",
        subject_type_code_raw: str = "",
        is_active: str = "1",
    ) -> str:
        subject_id = make_subject_uuid(source_system, source_dataset, source_primary_id)
        if subject_id not in self.ctx.subjects:
            subject = blank_row("sanction_subjects")
            subject.update(
                {
                    "subject_id": subject_id,
                    "source_system": source_system,
                    "source_dataset": source_dataset,
                    "subject_type": subject_type,
                    "subject_type_raw": clean(subject_type_raw),
                    "subject_type_code_raw": clean(subject_type_code_raw),
                    "primary_name": clean(primary_name),
                    "title": clean(title),
                    "gender": clean(gender),
                    "function_role": clean(function_role),
                    "designation_date": designation_date,
                    "designation_details_raw": clean(designation_details_raw),
                    "designation_source_raw": clean(designation_source_raw),
                    "entity_subtype_raw": clean(entity_subtype_raw),
                    "is_active": is_active,
                    "created_at": self.created_at,
                    "updated_at": self.created_at,
                }
            )
            self.ctx.subjects[subject_id] = subject
        else:
            self.set_subject_field(subject_id, "primary_name", primary_name)
            self.set_subject_field(subject_id, "title", title)
            self.set_subject_field(subject_id, "gender", gender)
            self.append_subject_field(subject_id, "function_role", function_role)
            self.set_subject_field(subject_id, "designation_date", designation_date)
            self.append_subject_field(subject_id, "designation_details_raw", designation_details_raw)
            self.append_subject_field(subject_id, "designation_source_raw", designation_source_raw)
            self.append_subject_field(subject_id, "entity_subtype_raw", entity_subtype_raw)
            self.set_subject_field(subject_id, "subject_type_code_raw", subject_type_code_raw)

        self.add_source_record(
            subject_id=subject_id,
            source_system=source_system,
            source_dataset=source_dataset,
            source_primary_id=source_primary_id,
            source_component_type="SUBJECT",
            source_component_id=source_primary_id,
        )
        return subject_id

    def set_subject_field(self, subject_id: str, field: str, value: str) -> None:
        text = clean_trailing(value)
        if not text:
            return
        subject = self.ctx.subjects[subject_id]
        if not subject.get(field):
            subject[field] = text

    def append_subject_field(self, subject_id: str, field: str, value: str) -> None:
        text = clean_trailing(value)
        if not text:
            return
        self.ctx.append_subject_field(subject_id, field, text)

    def add_source_record(
        self,
        subject_id: str,
        source_system: str,
        source_dataset: str,
        source_primary_id: str,
        source_component_type: str,
        source_component_id: str,
        source_secondary_id: str = "",
        source_tertiary_id: str = "",
        file_generation_date: str = "",
        report_date: str = "",
        version_num: str = "",
        list_type_raw: str = "",
        sort_key: str = "",
        sort_key_last_mod: str = "",
    ) -> None:
        dedup_key = (subject_id, source_component_type, source_component_id)
        if dedup_key in self.subject_source_records:
            existing = self.subject_source_record_rows[dedup_key]
            for field, value in {
                "source_secondary_id": source_secondary_id,
                "source_tertiary_id": source_tertiary_id,
                "file_generation_date": file_generation_date,
                "report_date": report_date,
                "version_num": version_num,
                "list_type_raw": list_type_raw,
                "sort_key": sort_key,
                "sort_key_last_mod": sort_key_last_mod,
            }.items():
                if value and not existing.get(field):
                    existing[field] = value
            return
        self.subject_source_records.add(dedup_key)
        row = {
            "source_record_id": stable_id(
                "subject_source_records",
                subject_id,
                source_component_type,
                source_component_id,
            ),
            "subject_id": subject_id,
            "source_system": source_system,
            "source_dataset": source_dataset,
            "source_primary_id": source_primary_id,
            "source_secondary_id": source_secondary_id,
            "source_tertiary_id": source_tertiary_id,
            "source_component_type": source_component_type,
            "source_component_id": source_component_id,
            "file_generation_date": file_generation_date,
            "report_date": report_date,
            "version_num": version_num,
            "list_type_raw": list_type_raw,
            "sort_key": sort_key,
            "sort_key_last_mod": sort_key_last_mod,
        }
        self.add_row("subject_source_records", row)
        self.subject_source_record_rows[dedup_key] = self.ctx.rows["subject_source_records"][-1]

    def add_primary_name_row(
        self,
        subject_id: str,
        full_name: str,
        name_parts: Optional[Sequence[str]] = None,
        non_latin_name: str = "",
        source_component_id: str = "PRIMARY",
    ) -> None:
        full_name = clean(full_name)
        if not full_name:
            return
        dedup = (subject_id, full_name, "PRIMARY")
        if dedup in self.subject_primary_names:
            return
        self.subject_primary_names.add(dedup)
        row = {
            "subject_name_id": stable_id("subject_names", subject_id, "PRIMARY", full_name, source_component_id),
            "subject_id": subject_id,
            "full_name": full_name,
            "name_type": "PRIMARY",
            "is_primary": "1",
            "non_latin_name": clean(non_latin_name),
            "source_component_id": source_component_id,
        }
        if name_parts:
            for idx, value in enumerate(name_parts[:6], 1):
                row[f"name_part_{idx}"] = clean(value)
        self.add_row("subject_names", row)
        self.subjects_with_primary_name.add(subject_id)

    def finalize_subjects(self) -> None:
        self.ctx.rows["sanction_subjects"] = list(self.ctx.subjects.values())


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_comments(path: Path) -> Dict[str, str]:
    comments: DefaultDict[str, List[str]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) >= 2:
                comments[clean(row[0])].append(row[1])
    return {key: "".join(parts) for key, parts in comments.items()}


def load_grouped_rows(path: Path, key_index: int = 0) -> DefaultDict[str, List[List[str]]]:
    grouped: DefaultDict[str, List[List[str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if row:
                grouped[clean(row[key_index])].append(row)
    return grouped


def apply_ofac_remark_rules(
    builder: PipelineBuilder,
    subject_id: str,
    merged_remark: str,
    source_dataset: str,
) -> None:
    for segment_index, segment in enumerate(split_remark_segments(merged_remark), 1):
        matched = False
        for rule in RULES:
            match = rule.regex.match(segment)
            if match:
                rule.handler(builder.ctx, subject_id, segment_index, segment, match)
                builder.ofac_rule_counts[f"{source_dataset}:{rule.name}"] += 1
                matched = True
                break
        if not matched:
            builder.unmapped_ofac_segments.append(
                {
                    "subject_id": subject_id,
                    "source_dataset": source_dataset,
                    "segment_index": str(segment_index),
                    "segment": segment,
                    "reason": "NO_EXPLICIT_SUPPORTED_PREFIX",
                }
            )
            builder.add_row(
                "subject_notes",
                {
                    "note_id": stable_id("subject_notes", subject_id, source_dataset, segment_index, segment),
                    "subject_id": subject_id,
                    "note_type": "REMARKS_UNPARSED_SEGMENT",
                    "note_text": segment,
                    "source_component_id": f"REMARKS:{segment_index}",
                },
            )


def parse_ofac_dataset(
    builder: PipelineBuilder,
    dataset_name: str,
    prim_path: Path,
    alt_path: Path,
    add_path: Path,
    comments_path: Path,
) -> None:
    comments = load_comments(comments_path)
    alt_rows = load_grouped_rows(alt_path)
    add_rows = load_grouped_rows(add_path)

    with prim_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) != 12:
                continue
            ent_num = clean(row[0])
            base_remark = row[11] if not nullish(row[11]) else ""
            spillover = comments.get(ent_num, "")
            merged_remark = f"{base_remark}{spillover}" if (base_remark or spillover) else ""

            subject_id = builder.ensure_subject(
                source_system="OFAC",
                source_dataset=dataset_name,
                source_primary_id=ent_num,
                subject_type=normalize_subject_type(row[2]),
                subject_type_raw=row[2],
                primary_name=row[1],
                title=row[4],
            )
            builder.add_primary_name_row(subject_id, clean(row[1]), source_component_id="SDN_NAME")

            builder.add_row(
                "subject_identifiers",
                {
                    "identifier_id": stable_id("subject_identifiers", subject_id, "OFAC_ENT_NUM", ent_num),
                    "subject_id": subject_id,
                    "identifier_type": "OFAC_ENT_NUM",
                    "identifier_value": ent_num,
                    "source_component_id": "SDN_ENT_NUM",
                },
            )

            for idx, program_name in enumerate(split_programs(row[3]), 1):
                builder.add_row(
                    "subject_programs",
                    {
                        "program_id": stable_id("subject_programs", subject_id, dataset_name, program_name),
                        "subject_id": subject_id,
                        "list_family": dataset_name,
                        "program_name": program_name,
                        "source_component_scope": "PRIMARY",
                        "source_component_id": f"PROGRAM:{idx}",
                    },
                )

            if any(not nullish(value) for value in row[5:11]):
                builder.add_row(
                    "subject_vessel_details",
                    {
                        "vessel_detail_id": stable_id("subject_vessel_details", subject_id),
                        "subject_id": subject_id,
                        "call_sign": clean(row[5]),
                        "vessel_type": clean(row[6]),
                        "tonnage": clean(row[7]),
                        "grt": clean(row[8]),
                        "flag_current": clean(row[9]),
                        "vessel_owner_raw": clean(row[10]),
                    },
                )

            if base_remark:
                builder.add_row(
                    "subject_notes",
                    {
                        "note_id": stable_id("subject_notes", subject_id, dataset_name, "REMARKS_RAW", base_remark),
                        "subject_id": subject_id,
                        "note_type": "REMARKS_RAW",
                        "note_text": base_remark,
                        "source_component_id": "REMARKS_RAW",
                    },
                )
            if spillover:
                builder.add_row(
                    "subject_notes",
                    {
                        "note_id": stable_id("subject_notes", subject_id, dataset_name, "REMARKS_SPILLOVER_RAW", spillover),
                        "subject_id": subject_id,
                        "note_type": "REMARKS_SPILLOVER_RAW",
                        "note_text": spillover,
                        "source_component_id": "REMARKS_SPILLOVER",
                    },
                )
            if merged_remark and merged_remark != base_remark:
                builder.add_row(
                    "subject_notes",
                    {
                        "note_id": stable_id("subject_notes", subject_id, dataset_name, "REMARKS_MERGED", merged_remark),
                        "subject_id": subject_id,
                        "note_type": "REMARKS_MERGED",
                        "note_text": merged_remark,
                        "source_component_id": "REMARKS_MERGED",
                    },
                )
            if merged_remark:
                apply_ofac_remark_rules(builder, subject_id, merged_remark, dataset_name)

            for alt in alt_rows.get(ent_num, []):
                alt_num = clean(alt[1])
                alt_name = clean(alt[3])
                if not alt_name:
                    continue
                builder.add_row(
                    "subject_names",
                    {
                        "subject_name_id": stable_id("subject_names", subject_id, alt_num, alt_name),
                        "subject_id": subject_id,
                        "full_name": alt_name,
                        "name_type": name_type_from_alt(alt[2]),
                        "is_primary": "0",
                        "note": clean(alt[4]),
                        "source_component_id": f"ALT:{alt_num}",
                    },
                )
                builder.add_source_record(
                    subject_id=subject_id,
                    source_system="OFAC",
                    source_dataset=dataset_name,
                    source_primary_id=ent_num,
                    source_component_type="ALT",
                    source_component_id=alt_num,
                )

            for add in add_rows.get(ent_num, []):
                add_num = clean(add[1])
                address_line_1 = clean(add[2])
                address_line_2 = clean(add[3])
                country_name = clean(add[4])
                note = clean(add[5])
                builder.add_row(
                    "subject_addresses",
                    {
                        "address_id": stable_id("subject_addresses", subject_id, add_num),
                        "subject_id": subject_id,
                        "address_full_raw": join_nonempty([address_line_1, address_line_2, country_name]),
                        "address_line_1": address_line_1,
                        "address_line_2": address_line_2,
                        "country_name": country_name,
                        "note": note,
                        "source_component_id": f"ADD:{add_num}",
                    },
                )
                builder.add_source_record(
                    subject_id=subject_id,
                    source_system="OFAC",
                    source_dataset=dataset_name,
                    source_primary_id=ent_num,
                    source_component_type="ADD",
                    source_component_id=add_num,
                )


def parse_eu(builder: PipelineBuilder, path: Path) -> None:
    dataset_name = path.stem
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            entity_id = clean(row.get("Entity_LogicalId", ""))
            if not entity_id:
                continue
            subject_id = builder.ensure_subject(
                source_system="EU",
                source_dataset=dataset_name,
                source_primary_id=entity_id,
                subject_type=eu_subject_type(row.get("Entity_SubjectType", "")),
                subject_type_raw=row.get("Entity_SubjectType", ""),
                subject_type_code_raw=row.get("Entity_SubjectType_ClassificationCode", ""),
                primary_name="",
                designation_date=parse_date(row.get("Entity_DesignationDate", "")),
                designation_details_raw=row.get("Entity_DesignationDetails", ""),
            )
            builder.add_source_record(
                subject_id=subject_id,
                source_system="EU",
                source_dataset=dataset_name,
                source_primary_id=entity_id,
                source_component_type="ENTITY",
                source_component_id=entity_id,
                file_generation_date=parse_date(row.get("fileGenerationDate", "")),
            )

            builder.add_row(
                "subject_identifiers",
                {
                    "identifier_id": stable_id("subject_identifiers", subject_id, "EU_ENTITY_ID", entity_id),
                    "subject_id": subject_id,
                    "identifier_type": "EU_ENTITY_ID",
                    "identifier_value": entity_id,
                    "source_component_id": "ENTITY_LOGICAL_ID",
                },
            )
            if clean(row.get("Entity_EU_ReferenceNumber", "")):
                builder.add_row(
                    "subject_identifiers",
                    {
                        "identifier_id": stable_id("subject_identifiers", subject_id, "EU_REFERENCE", row["Entity_EU_ReferenceNumber"]),
                        "subject_id": subject_id,
                        "identifier_type": "EU_REFERENCE",
                        "identifier_value": clean(row["Entity_EU_ReferenceNumber"]),
                        "source_component_id": "ENTITY_EU_REFERENCE",
                    },
                )
            if clean(row.get("Entity_UnitedNationId", "")):
                builder.add_row(
                    "subject_identifiers",
                    {
                        "identifier_id": stable_id("subject_identifiers", subject_id, "UN_REFERENCE", row["Entity_UnitedNationId"]),
                        "subject_id": subject_id,
                        "identifier_type": "UN_REFERENCE",
                        "identifier_value": clean(row["Entity_UnitedNationId"]),
                        "source_component_id": "ENTITY_UN_REFERENCE",
                    },
                )

            builder.append_subject_field(subject_id, "designation_details_raw", row.get("Entity_DesignationDetails", ""))
            if clean(row.get("Entity_Remark", "")):
                builder.add_row(
                    "subject_notes",
                    {
                        "note_id": stable_id("subject_notes", subject_id, "ENTITY_REMARK", row["Entity_Remark"]),
                        "subject_id": subject_id,
                        "note_type": "ENTITY_REMARK",
                        "note_text": clean(row["Entity_Remark"]),
                        "source_component_id": "ENTITY_REMARK",
                    },
                )

            whole_name, last_name, first_name, middle_name = eu_name_fields(row)
            name_component = clean(row.get("NameAlias_LogicalId", ""))
            if whole_name or name_component:
                is_primary = subject_id not in builder.subjects_with_primary_name
                builder.add_row(
                    "subject_names",
                    {
                        "subject_name_id": stable_id("subject_names", subject_id, name_component or whole_name, whole_name, "EU"),
                        "subject_id": subject_id,
                        "full_name": whole_name,
                        "name_part_1": last_name,
                        "name_part_2": first_name,
                        "name_part_3": middle_name,
                        "name_type": "PRIMARY" if is_primary else "ALIAS",
                        "is_primary": "1" if is_primary else "0",
                        "language_code": clean(row.get("NameAlias_NameLanguage", "")),
                        "note": clean(row.get("NameAlias_Remark", "")),
                        "source_component_id": name_component,
                    },
                )
                if is_primary and whole_name:
                    builder.set_subject_field(subject_id, "primary_name", whole_name)
                    builder.subjects_with_primary_name.add(subject_id)
                builder.set_subject_field(subject_id, "gender", row.get("NameAlias_Gender", ""))
                builder.set_subject_field(subject_id, "title", row.get("NameAlias_Title", ""))
                builder.append_subject_field(subject_id, "function_role", row.get("NameAlias_Function", ""))
                if name_component:
                    builder.add_source_record(
                        subject_id=subject_id,
                        source_system="EU",
                        source_dataset=dataset_name,
                        source_primary_id=entity_id,
                        source_component_type="NAME_ALIAS",
                        source_component_id=name_component,
                        file_generation_date=parse_date(row.get("fileGenerationDate", "")),
                    )
                builder.add_eu_regulation_and_program_rows(
                    subject_id,
                    "NAME_ALIAS",
                    name_component,
                    {
                        "regulation_type": row.get("NameAlias_Regulation_Type", ""),
                        "organisation_type": row.get("NameAlias_Regulation_OrganisationType", ""),
                        "publication_date": row.get("NameAlias_Regulation_PublicationDate", ""),
                        "entry_into_force_date": row.get("NameAlias_Regulation_EntryIntoForceDate", ""),
                        "number_title": row.get("NameAlias_Regulation_NumberTitle", ""),
                        "program_name": row.get("NameAlias_Regulation_Programme", ""),
                        "publication_url": row.get("NameAlias_Regulation_PublicationUrl", ""),
                        "regulation_language": row.get("NameAlias_RegulationLanguage", ""),
                    },
                )

            address_component = clean(row.get("Address_LogicalId", ""))
            if address_component or join_nonempty(
                [
                    row.get("Address_Street", ""),
                    row.get("Address_City", ""),
                    row.get("Address_ZipCode", ""),
                    row.get("Address_CountryDescription", ""),
                ]
            ):
                builder.add_row(
                    "subject_addresses",
                    {
                        "address_id": stable_id("subject_addresses", subject_id, address_component or join_nonempty([row.get("Address_Street", ""), row.get("Address_City", ""), row.get("Address_CountryDescription", "")])),
                        "subject_id": subject_id,
                        "address_full_raw": join_nonempty(
                            [
                                row.get("Address_Street", ""),
                                row.get("Address_PoBox", ""),
                                row.get("Address_City", ""),
                                row.get("Address_Region", ""),
                                row.get("Address_Place", ""),
                                row.get("Address_ZipCode", ""),
                                row.get("Address_CountryDescription", ""),
                            ]
                        ),
                        "street": clean(row.get("Address_Street", "")),
                        "po_box": clean(row.get("Address_PoBox", "")),
                        "city": clean(row.get("Address_City", "")),
                        "region": clean(row.get("Address_Region", "")),
                        "place": clean(row.get("Address_Place", "")),
                        "postal_code": clean(row.get("Address_ZipCode", "")),
                        "country_code": clean(row.get("Address_CountryIso2Code", "")),
                        "country_name": clean(row.get("Address_CountryDescription", "")),
                        "as_at_listing_time": clean(row.get("Address_AsAtListingTime", "")),
                        "contact_info": clean(row.get("Address_ContactInfo", "")),
                        "note": clean(row.get("Address_Remark", "")),
                        "source_component_id": address_component,
                    },
                )
                if address_component:
                    builder.add_source_record(
                        subject_id=subject_id,
                        source_system="EU",
                        source_dataset=dataset_name,
                        source_primary_id=entity_id,
                        source_component_type="ADDRESS",
                        source_component_id=address_component,
                        file_generation_date=parse_date(row.get("fileGenerationDate", "")),
                    )
                builder.add_eu_regulation_and_program_rows(
                    subject_id,
                    "ADDRESS",
                    address_component,
                    {
                        "regulation_type": row.get("Address_Regulation_Type", ""),
                        "organisation_type": row.get("Address_Regulation_OrganisationType", ""),
                        "publication_date": row.get("Address_Regulation_PublicationDate", ""),
                        "entry_into_force_date": row.get("Address_Regulation_EntryIntoForceDate", ""),
                        "number_title": row.get("Address_Regulation_NumberTitle", ""),
                        "program_name": row.get("Address_Regulation_Programme", ""),
                        "publication_url": row.get("Address_Regulation_PublicationUrl", ""),
                        "regulation_language": row.get("Address_RegulationLanguage", ""),
                    },
                )

            birth_component = clean(row.get("BirthDate_LogicalId", ""))
            if birth_component or clean(row.get("BirthDate_BirthDate", "")) or clean(row.get("BirthDate_Year", "")):
                builder.add_row(
                    "subject_birth_dates",
                    {
                        "birth_date_id": stable_id("subject_birth_dates", subject_id, birth_component or row.get("BirthDate_BirthDate", "")),
                        "subject_id": subject_id,
                        "birth_date": parse_date(row.get("BirthDate_BirthDate", "")),
                        "day": clean(row.get("BirthDate_Day", "")),
                        "month": clean(row.get("BirthDate_Month", "")),
                        "year": clean(row.get("BirthDate_Year", "")),
                        "year_from": clean(row.get("BirthDate_YearRangeFrom", "")),
                        "year_to": clean(row.get("BirthDate_YearRangeTo", "")),
                        "circa_flag": to_flag(row.get("BirthDate_Circa", "")),
                        "calendar_type": clean(row.get("BirthDate_CalendarType", "")),
                        "date_type_raw": "",
                        "is_incomplete": "1" if not clean(row.get("BirthDate_BirthDate", "")) else "0",
                        "note": clean(row.get("BirthDate_Remark", "")),
                        "source_component_id": birth_component,
                    },
                )
                builder.add_row(
                    "subject_birth_places",
                    {
                        "birth_place_id": stable_id("subject_birth_places", subject_id, birth_component or row.get("BirthDate_Place", "")),
                        "subject_id": subject_id,
                        "place": clean(row.get("BirthDate_Place", "")),
                        "city": clean(row.get("BirthDate_City", "")),
                        "region": clean(row.get("BirthDate_Region", "")),
                        "postal_code": clean(row.get("BirthDate_ZipCode", "")),
                        "country_code": clean(row.get("BirthDate_CountryIso2Code", "")),
                        "country_name": clean(row.get("BirthDate_CountryDescription", "")),
                        "note": clean(row.get("BirthDate_Remark", "")),
                        "source_component_id": birth_component,
                    },
                )
                if birth_component:
                    builder.add_source_record(
                        subject_id=subject_id,
                        source_system="EU",
                        source_dataset=dataset_name,
                        source_primary_id=entity_id,
                        source_component_type="BIRTHDATE",
                        source_component_id=birth_component,
                        file_generation_date=parse_date(row.get("fileGenerationDate", "")),
                    )
                builder.add_eu_regulation_and_program_rows(
                    subject_id,
                    "BIRTHDATE",
                    birth_component,
                    {
                        "regulation_type": row.get("BirthDate_Regulation_Type", ""),
                        "organisation_type": row.get("BirthDate_Regulation_OrganisationType", ""),
                        "publication_date": row.get("BirthDate_Regulation_PublicationDate", ""),
                        "entry_into_force_date": row.get("BirthDate_Regulation_EntryIntoForceDate", ""),
                        "number_title": row.get("BirthDate_Regulation_NumberTitle", ""),
                        "program_name": row.get("BirthDate_Regulation_Programme", ""),
                        "publication_url": row.get("BirthDate_Regulation_PublicationUrl", ""),
                        "regulation_language": row.get("BirthDate_RegulationLanguage", ""),
                    },
                )

            identification_component = clean(row.get("Identification_LogicalId", ""))
            if identification_component or clean(row.get("Identification_Number", "")):
                builder.add_row(
                    "subject_identifiers",
                    {
                        "identifier_id": stable_id("subject_identifiers", subject_id, identification_component or row.get("Identification_Number", "")),
                        "subject_id": subject_id,
                        "identifier_type": parse_eu_identifier_type(
                            row.get("Identification_TypeCode", ""),
                            row.get("Identification_TypeDescription", ""),
                        ),
                        "identifier_value": clean(row.get("Identification_Number", "")),
                        "identifier_value_latin": clean(row.get("Identification_LatinNumber", "")),
                        "name_on_document": clean(row.get("Identification_NameOnDocument", "")),
                        "issued_by": clean(row.get("Identification_IssuedBy", "")),
                        "issuing_country_code": clean(row.get("Identification_CountryIso2Code", "")),
                        "issuing_country_name": clean(row.get("Identification_CountryDescription", "")),
                        "issued_date": parse_date(row.get("Identification_IssuedDate", "")),
                        "valid_from": parse_date(row.get("Identification_ValidFrom", "")),
                        "valid_to": parse_date(row.get("Identification_ValidTo", "")),
                        "is_diplomatic": to_flag(row.get("Identification_Diplomatic", "")),
                        "is_known_expired": to_flag(row.get("Identification_KnownExpired", "")),
                        "is_known_false": to_flag(row.get("Identification_KnownFalse", "")),
                        "is_reported_lost": to_flag(row.get("Identification_ReportedLost", "")),
                        "is_revoked_by_issuer": to_flag(row.get("Identification_RevokedByIssuer", "")),
                        "additional_information": join_nonempty(
                            [
                                f"type_code={clean(row.get('Identification_TypeCode', ''))}",
                                f"type_description={clean(row.get('Identification_TypeDescription', ''))}",
                                f"region={clean(row.get('Identification_Region', ''))}",
                                f"remark={clean(row.get('Identification_Remark', ''))}",
                            ],
                            sep=" | ",
                        ),
                        "source_component_id": identification_component,
                    },
                )
                if identification_component:
                    builder.add_source_record(
                        subject_id=subject_id,
                        source_system="EU",
                        source_dataset=dataset_name,
                        source_primary_id=entity_id,
                        source_component_type="IDENTIFICATION",
                        source_component_id=identification_component,
                        file_generation_date=parse_date(row.get("fileGenerationDate", "")),
                    )
                builder.add_eu_regulation_and_program_rows(
                    subject_id,
                    "IDENTIFICATION",
                    identification_component,
                    {
                        "regulation_type": row.get("Identification_Regulation_Type", ""),
                        "organisation_type": row.get("Identification_Regulation_OrganisationType", ""),
                        "publication_date": row.get("Identification_Regulation_PublicationDate", ""),
                        "entry_into_force_date": row.get("Identification_Regulation_EntryIntoForceDate", ""),
                        "number_title": row.get("Identification_Regulation_NumberTitle", ""),
                        "program_name": row.get("Identification_Regulation_Programme", ""),
                        "publication_url": row.get("Identification_Regulation_PublicationUrl", ""),
                        "regulation_language": row.get("Identification_RegulationLanguage", ""),
                    },
                )

            citizenship_component = clean(row.get("Citizenship_LogicalId", ""))
            if citizenship_component or clean(row.get("Citizenship_CountryDescription", "")):
                builder.add_row(
                    "subject_nationalities",
                    {
                        "nationality_id": stable_id("subject_nationalities", subject_id, citizenship_component or row.get("Citizenship_CountryDescription", "")),
                        "subject_id": subject_id,
                        "country_code": clean(row.get("Citizenship_CountryIso2Code", "")),
                        "country_name": clean(row.get("Citizenship_CountryDescription", "")),
                        "region": clean(row.get("Citizenship_Region", "")),
                        "nationality_raw": clean(row.get("Citizenship_CountryDescription", "")),
                        "note": clean(row.get("Citizenship_Remark", "")),
                        "source_component_id": citizenship_component,
                    },
                )
                if citizenship_component:
                    builder.add_source_record(
                        subject_id=subject_id,
                        source_system="EU",
                        source_dataset=dataset_name,
                        source_primary_id=entity_id,
                        source_component_type="CITIZENSHIP",
                        source_component_id=citizenship_component,
                        file_generation_date=parse_date(row.get("fileGenerationDate", "")),
                    )
                builder.add_eu_regulation_and_program_rows(
                    subject_id,
                    "CITIZENSHIP",
                    citizenship_component,
                    {
                        "regulation_type": row.get("Citizenship_Regulation_Type", ""),
                        "organisation_type": row.get("Citizenship_Regulation_OrganisationType", ""),
                        "publication_date": row.get("Citizenship_Regulation_PublicationDate", ""),
                        "entry_into_force_date": row.get("Citizenship_Regulation_EntryIntoForceDate", ""),
                        "number_title": row.get("Citizenship_Regulation_NumberTitle", ""),
                        "program_name": row.get("Citizenship_Regulation_Programme", ""),
                        "publication_url": row.get("Citizenship_Regulation_PublicationUrl", ""),
                        "regulation_language": row.get("Citizenship_RegulationLanguage", ""),
                    },
                )

            builder.add_eu_regulation_and_program_rows(
                subject_id,
                "ENTITY",
                entity_id,
                {
                    "regulation_type": row.get("Entity_Regulation_Type", ""),
                    "organisation_type": row.get("Entity_Regulation_OrganisationType", ""),
                    "publication_date": row.get("Entity_Regulation_PublicationDate", ""),
                    "entry_into_force_date": row.get("Entity_Regulation_EntryIntoForceDate", ""),
                    "number_title": row.get("Entity_Regulation_NumberTitle", ""),
                    "program_name": row.get("Entity_Regulation_Programme", ""),
                    "publication_url": row.get("Entity_Regulation_PublicationUrl", ""),
                    "regulation_language": "",
                },
            )


def add_eu_regulation_and_program_rows(
    builder: PipelineBuilder,
    subject_id: str,
    scope: str,
    source_component_id: str,
    reg: Dict[str, str],
) -> None:
    program_name = clean(reg.get("program_name", ""))
    if program_name:
        builder.add_row(
            "subject_programs",
            {
                "program_id": stable_id("subject_programs", subject_id, scope, source_component_id, program_name),
                "subject_id": subject_id,
                "list_family": "EU",
                "program_name": program_name,
                "source_component_scope": scope,
                "source_component_id": source_component_id,
            },
        )
    regulation_fields = [
        clean(reg.get("regulation_type", "")),
        clean(reg.get("organisation_type", "")),
        clean(reg.get("publication_date", "")),
        clean(reg.get("entry_into_force_date", "")),
        clean(reg.get("number_title", "")),
        clean(reg.get("publication_url", "")),
        clean(reg.get("regulation_language", "")),
    ]
    if any(regulation_fields):
        builder.add_row(
            "subject_regulations",
            {
                "regulation_id": stable_id("subject_regulations", subject_id, scope, source_component_id, *regulation_fields),
                "subject_id": subject_id,
                "regulation_scope": scope,
                "regulation_type": clean(reg.get("regulation_type", "")),
                "organisation_type": clean(reg.get("organisation_type", "")),
                "publication_date": parse_date(reg.get("publication_date", "")),
                "entry_into_force_date": parse_date(reg.get("entry_into_force_date", "")),
                "number_title": clean(reg.get("number_title", "")),
                "publication_url": clean(reg.get("publication_url", "")),
                "regulation_language": clean(reg.get("regulation_language", "")),
                "source_component_id": source_component_id,
            },
        )


PipelineBuilder.add_eu_regulation_and_program_rows = add_eu_regulation_and_program_rows


def parse_uk(builder: PipelineBuilder, path: Path) -> None:
    dataset_name = path.stem
    with path.open(newline="", encoding="utf-8-sig") as handle:
        raw_reader = csv.reader(handle)
        report_line = next(raw_reader)[0]
        headers = next(raw_reader)
        report_date = parse_report_date(report_line)

        for row_number, values in enumerate(raw_reader, 1):
            row = dict(zip(headers, values))
            unique_id = clean(row.get("Unique ID", ""))
            if not unique_id:
                continue
            primary_name = uk_primary_name(row)
            subject_id = builder.ensure_subject(
                source_system="UK",
                source_dataset=dataset_name,
                source_primary_id=unique_id,
                subject_type=uk_subject_type(row.get("Designation Type", "")),
                subject_type_raw=row.get("Designation Type", ""),
                primary_name=primary_name,
                title=row.get("Title", ""),
                gender=row.get("Gender", ""),
                function_role=row.get("Position", ""),
                designation_date=parse_date(row.get("Date Designated", "")),
                designation_source_raw=row.get("Designation source", ""),
                entity_subtype_raw=row.get("Type of entity", ""),
            )
            builder.add_source_record(
                subject_id=subject_id,
                source_system="UK",
                source_dataset=dataset_name,
                source_primary_id=unique_id,
                source_secondary_id=clean(row.get("OFSI Group ID", "")),
                source_tertiary_id=clean(row.get("UN Reference Number", "")),
                source_component_type="ROW",
                source_component_id=f"ROW:{row_number}",
                report_date=report_date,
            )
            builder.add_source_record(
                subject_id=subject_id,
                source_system="UK",
                source_dataset=dataset_name,
                source_primary_id=unique_id,
                source_secondary_id=clean(row.get("OFSI Group ID", "")),
                source_tertiary_id=clean(row.get("UN Reference Number", "")),
                source_component_type="SUBJECT",
                source_component_id=unique_id,
                report_date=report_date,
            )

            for identifier_type, value, extra in [
                ("UK_UNIQUE_ID", row.get("Unique ID", ""), ""),
                ("UK_OFSI_GROUP_ID", row.get("OFSI Group ID", ""), ""),
                ("UN_REFERENCE", row.get("UN Reference Number", ""), ""),
            ]:
                if clean(value):
                    builder.add_row(
                        "subject_identifiers",
                        {
                            "identifier_id": stable_id("subject_identifiers", subject_id, identifier_type, value),
                            "subject_id": subject_id,
                            "identifier_type": identifier_type,
                            "identifier_value": clean(value),
                            "additional_information": extra,
                            "source_component_id": f"ROW:{row_number}",
                        },
                    )

            row_has_name_payload = any(
                clean(row.get(key, ""))
                for key in [*(f"Name {idx}" for idx in range(1, 7)), "Name non-latin script"]
            )
            if primary_name or row_has_name_payload:
                is_primary_name_row = subject_id not in builder.subjects_with_primary_name and bool(primary_name)
                if is_primary_name_row:
                    builder.subjects_with_primary_name.add(subject_id)
                raw_name_type = clean(row.get("Name type", ""))
                name_note = f"raw_name_type={raw_name_type}" if raw_name_type else ""
                builder.add_row(
                    "subject_names",
                    {
                        "subject_name_id": stable_id("subject_names", subject_id, primary_name, raw_name_type or "UK", row.get("Name non-latin script", "")),
                        "subject_id": subject_id,
                        "full_name": primary_name,
                        "name_part_1": clean(row.get("Name 1", "")),
                        "name_part_2": clean(row.get("Name 2", "")),
                        "name_part_3": clean(row.get("Name 3", "")),
                        "name_part_4": clean(row.get("Name 4", "")),
                        "name_part_5": clean(row.get("Name 5", "")),
                        "name_part_6": clean(row.get("Name 6", "")),
                        "name_type": uk_name_type(raw_name_type, is_primary_name_row),
                        "alias_strength": clean(row.get("Alias strength", "")),
                        "is_primary": "1" if is_primary_name_row else "0",
                        "non_latin_name": clean(row.get("Name non-latin script", "")),
                        "non_latin_script_type": clean(row.get("Non-latin script type", "")),
                        "non_latin_language": clean(row.get("Non-latin script language", "")),
                        "note": name_note,
                        "source_component_id": f"ROW:{row_number}",
                    },
                )

            address_full = join_nonempty(
                [row.get(f"Address Line {idx}", "") for idx in range(1, 7)] + [row.get("Address Country", "")]
            )
            if address_full or clean(row.get("Address Postal Code", "")):
                builder.add_row(
                    "subject_addresses",
                    {
                        "address_id": stable_id("subject_addresses", subject_id, row_number, address_full),
                        "subject_id": subject_id,
                        "address_full_raw": address_full,
                        "address_line_1": clean(row.get("Address Line 1", "")),
                        "address_line_2": clean(row.get("Address Line 2", "")),
                        "address_line_3": clean(row.get("Address Line 3", "")),
                        "address_line_4": clean(row.get("Address Line 4", "")),
                        "address_line_5": clean(row.get("Address Line 5", "")),
                        "address_line_6": clean(row.get("Address Line 6", "")),
                        "postal_code": clean(row.get("Address Postal Code", "")),
                        "country_name": clean(row.get("Address Country", "")),
                        "source_component_id": f"ROW:{row_number}",
                    },
                )

            for contact_type, value in [
                ("PHONE", row.get("Phone number", "")),
                ("WEBSITE", row.get("Website", "")),
                ("EMAIL", row.get("Email address", "")),
            ]:
                if clean(value):
                    builder.add_row(
                        "subject_contacts",
                        {
                            "contact_id": stable_id("subject_contacts", subject_id, contact_type, value),
                            "subject_id": subject_id,
                            "contact_type": contact_type,
                            "contact_value": clean(value),
                        },
                    )

            for raw_value in split_multi(row.get("D.O.B", "")):
                parsed = parse_uk_birth_value(raw_value)
                builder.add_row(
                    "subject_birth_dates",
                    {
                        "birth_date_id": stable_id("subject_birth_dates", subject_id, raw_value),
                        "subject_id": subject_id,
                        "birth_date": parsed["birth_date"],
                        "day": parsed["day"],
                        "month": parsed["month"],
                        "year": parsed["year"],
                        "year_from": parsed["year_from"],
                        "year_to": parsed["year_to"],
                        "circa_flag": parsed["circa_flag"],
                        "calendar_type": parsed["calendar_type"],
                        "date_type_raw": parsed["date_type_raw"],
                        "is_incomplete": parsed["is_incomplete"],
                        "note": raw_value,
                        "source_component_id": f"ROW:{row_number}",
                    },
                )

            if clean(row.get("Town of birth", "")) or clean(row.get("Country of birth", "")):
                builder.add_row(
                    "subject_birth_places",
                    {
                        "birth_place_id": stable_id("subject_birth_places", subject_id, row_number, row.get("Town of birth", ""), row.get("Country of birth", "")),
                        "subject_id": subject_id,
                        "city": clean(row.get("Town of birth", "")),
                        "country_name": clean(row.get("Country of birth", "")),
                        "source_component_id": f"ROW:{row_number}",
                    },
                )

            for nationality in split_multi(row.get("Nationality(/ies)", "")):
                builder.add_row(
                    "subject_nationalities",
                    {
                        "nationality_id": stable_id("subject_nationalities", subject_id, nationality),
                        "subject_id": subject_id,
                        "country_name": nationality if nationality in COUNTRY_HINTS else "",
                        "nationality_raw": nationality,
                        "source_component_id": f"ROW:{row_number}",
                    },
                )

            for identifier_type, values, additional in [
                ("NATIONAL_ID", split_multi(row.get("National Identifier number", "")), row.get("National Identifier additional information", "")),
                ("PASSPORT", split_multi(row.get("Passport number", "")), row.get("Passport additional information", "")),
                ("BUSINESS_REGISTRATION", split_multi(row.get("Business registration number (s)", "")), ""),
            ]:
                for item in values:
                    builder.add_row(
                        "subject_identifiers",
                        {
                            "identifier_id": stable_id("subject_identifiers", subject_id, identifier_type, item),
                            "subject_id": subject_id,
                            "identifier_type": identifier_type,
                            "identifier_value": item,
                            "additional_information": clean(additional),
                            "source_component_id": f"ROW:{row_number}",
                        },
                    )

            if clean(row.get("IMO number", "")):
                builder.add_row(
                    "subject_identifiers",
                    {
                        "identifier_id": stable_id("subject_identifiers", subject_id, "IMO_NUMBER", row["IMO number"]),
                        "subject_id": subject_id,
                        "identifier_type": "IMO_NUMBER",
                        "identifier_value": clean(row["IMO number"]),
                        "source_component_id": f"ROW:{row_number}",
                    },
                )

            for regime in split_multi(row.get("Regime Name", "")):
                builder.add_row(
                    "subject_programs",
                    {
                        "program_id": stable_id("subject_programs", subject_id, "UKSL", regime),
                        "subject_id": subject_id,
                        "list_family": "UKSL",
                        "regime_name": regime,
                        "source_component_scope": "ROW",
                        "source_component_id": f"ROW:{row_number}",
                    },
                )

            for measure in split_multi(row.get("Sanctions Imposed", "")):
                builder.add_row(
                    "subject_measures",
                    {
                        "measure_id": stable_id("subject_measures", subject_id, measure),
                        "subject_id": subject_id,
                        "measure_type": "",
                        "measure_raw_text": measure,
                    },
                )

            for note_type, value in [
                ("OTHER_INFORMATION", row.get("Other Information", "")),
                ("STATEMENT_OF_REASONS", row.get("UK Statement of Reasons", "")),
            ]:
                if clean(value):
                    builder.add_row(
                        "subject_notes",
                        {
                            "note_id": stable_id("subject_notes", subject_id, note_type, value),
                            "subject_id": subject_id,
                            "note_type": note_type,
                            "note_text": clean(value),
                            "source_component_id": f"ROW:{row_number}",
                        },
                    )

            for relationship_type, value in [
                ("SUBSIDIARY", row.get("Subsidiaries", "")),
                ("PARENT_COMPANY", row.get("Parent company", "")),
                ("CURRENT_OWNER_OPERATOR", row.get("Current owner/operator (s)", "")),
                ("PREVIOUS_OWNER_OPERATOR", row.get("Previous owner/operator (s)", "")),
            ]:
                for item in split_multi(value):
                    builder.add_row(
                        "subject_relationships",
                        {
                            "relationship_id": stable_id("subject_relationships", subject_id, relationship_type, item),
                            "subject_id": subject_id,
                            "relationship_type": relationship_type,
                            "related_name": item,
                            "source_component_id": f"ROW:{row_number}",
                        },
                    )

            vessel_values = {
                "imo_number": row.get("IMO number", ""),
                "flag_current": row.get("Current believed flag of ship", ""),
                "flags_previous_raw": row.get("Previous flags", ""),
                "vessel_type": row.get("Type of ship", ""),
                "tonnage": row.get("Tonnage of ship", ""),
                "length": row.get("Length of ship", ""),
                "year_built": row.get("Year Built", ""),
                "hull_id": row.get("Hull identification number (HIN)", ""),
                "owner_operator_current_raw": row.get("Current owner/operator (s)", ""),
                "owner_operator_previous_raw": row.get("Previous owner/operator (s)", ""),
            }
            if any(clean(value) for value in vessel_values.values()):
                builder.add_row(
                    "subject_vessel_details",
                    {
                        "vessel_detail_id": stable_id("subject_vessel_details", subject_id),
                        "subject_id": subject_id,
                        **{field: clean(value) for field, value in vessel_values.items()},
                    },
                )

            if clean(row.get("Last Updated", "")):
                builder.add_row(
                    "subject_update_events",
                    {
                        "update_id": stable_id("subject_update_events", subject_id, row.get("Last Updated", "")),
                        "subject_id": subject_id,
                        "update_date": parse_date(row.get("Last Updated", "")),
                        "update_type_raw": "LAST_UPDATED",
                        "note": clean(row.get("Last Updated", "")),
                    },
                )


def parse_un(builder: PipelineBuilder, path: Path) -> None:
    dataset_name = "UN_CONSOLIDATED"
    root = ET.parse(path).getroot()

    for section_name, subject_type in [("INDIVIDUALS", "INDIVIDUAL"), ("ENTITIES", "ENTITY")]:
        section = root.find(section_name)
        if section is None:
            continue
        for node in section:
            data_id = clean(node.findtext("DATAID", ""))
            if not data_id:
                continue
            primary_name, name_parts = un_full_name(node)
            subject_id = builder.ensure_subject(
                source_system="UN",
                source_dataset=dataset_name,
                source_primary_id=data_id,
                subject_type=subject_type,
                subject_type_raw=subject_type,
                primary_name=primary_name,
                title=node.findtext("TITLE", ""),
                gender=node.findtext("GENDER", ""),
                function_role=node.findtext("DESIGNATION/VALUE", ""),
                designation_date=parse_date(node.findtext("LISTED_ON", "")),
            )
            builder.add_primary_name_row(
                subject_id,
                primary_name,
                name_parts=name_parts,
                non_latin_name=node.findtext("NAME_ORIGINAL_SCRIPT", ""),
                source_component_id="PRIMARY",
            )
            builder.add_source_record(
                subject_id=subject_id,
                source_system="UN",
                source_dataset=dataset_name,
                source_primary_id=data_id,
                source_secondary_id=clean(node.findtext("REFERENCE_NUMBER", "")),
                source_component_type="SUBJECT",
                source_component_id=data_id,
                version_num=clean(node.findtext("VERSIONNUM", "")),
                list_type_raw=clean(node.findtext("LIST_TYPE/VALUE", "") or node.findtext("LIST_TYPE", "")),
                sort_key=clean(node.findtext("SORT_KEY", "")),
                sort_key_last_mod=clean(node.findtext("SORT_KEY_LAST_MOD", "")),
            )

            if clean(node.findtext("REFERENCE_NUMBER", "")):
                builder.add_row(
                    "subject_identifiers",
                    {
                        "identifier_id": stable_id("subject_identifiers", subject_id, "UN_REFERENCE", node.findtext("REFERENCE_NUMBER", "")),
                        "subject_id": subject_id,
                        "identifier_type": "UN_REFERENCE",
                        "identifier_value": clean(node.findtext("REFERENCE_NUMBER", "")),
                        "source_component_id": "REFERENCE_NUMBER",
                    },
                )

            for alias_index, alias in enumerate(node.findall("INDIVIDUAL_ALIAS") + node.findall("ENTITY_ALIAS"), 1):
                alias_name = clean(alias.findtext("ALIAS_NAME", ""))
                if not alias_name:
                    continue
                extras = []
                for child in alias:
                    if child.tag not in {"ALIAS_NAME", "QUALITY"} and clean(child.text or ""):
                        extras.append(f"{child.tag}={clean(child.text or '')}")
                builder.add_row(
                    "subject_names",
                    {
                        "subject_name_id": stable_id("subject_names", subject_id, alias_index, alias_name),
                        "subject_id": subject_id,
                        "full_name": alias_name,
                        "name_type": "ALIAS",
                        "name_quality": clean(alias.findtext("QUALITY", "")),
                        "is_primary": "0",
                        "note": " | ".join(extras),
                        "source_component_id": f"ALIAS:{alias_index}",
                    },
                )

            for address_index, address in enumerate(node.findall("INDIVIDUAL_ADDRESS") + node.findall("ENTITY_ADDRESS"), 1):
                values = {child.tag: clean(child.text or "") for child in address}
                address_full = join_nonempty(
                    [
                        values.get("STREET", ""),
                        values.get("CITY", ""),
                        values.get("STATE_PROVINCE", ""),
                        values.get("ZIP_CODE", ""),
                        values.get("COUNTRY", ""),
                    ]
                )
                if not any(values.values()):
                    continue
                builder.add_row(
                    "subject_addresses",
                    {
                        "address_id": stable_id("subject_addresses", subject_id, address_index, address_full),
                        "subject_id": subject_id,
                        "address_full_raw": address_full,
                        "street": values.get("STREET", ""),
                        "city": values.get("CITY", ""),
                        "state_province": values.get("STATE_PROVINCE", ""),
                        "postal_code": values.get("ZIP_CODE", ""),
                        "country_name": values.get("COUNTRY", ""),
                        "note": values.get("NOTE", ""),
                        "source_component_id": f"ADDRESS:{address_index}",
                    },
                )

            for dob_index, dob in enumerate(node.findall("INDIVIDUAL_DATE_OF_BIRTH"), 1):
                values = {child.tag: clean(child.text or "") for child in dob}
                if not any(values.values()):
                    continue
                builder.add_row(
                    "subject_birth_dates",
                    {
                        "birth_date_id": stable_id("subject_birth_dates", subject_id, dob_index, values.get("DATE", ""), values.get("YEAR", "")),
                        "subject_id": subject_id,
                        "birth_date": parse_date(values.get("DATE", "")),
                        "year": values.get("YEAR", ""),
                        "year_from": values.get("FROM_YEAR", ""),
                        "year_to": values.get("TO_YEAR", ""),
                        "date_type_raw": values.get("TYPE_OF_DATE", ""),
                        "is_incomplete": "1" if not values.get("DATE") else "0",
                        "note": values.get("NOTE", ""),
                        "source_component_id": f"DOB:{dob_index}",
                    },
                )

            for pob_index, pob in enumerate(node.findall("INDIVIDUAL_PLACE_OF_BIRTH"), 1):
                values = {child.tag: clean(child.text or "") for child in pob}
                if not any(values.values()):
                    continue
                builder.add_row(
                    "subject_birth_places",
                    {
                        "birth_place_id": stable_id("subject_birth_places", subject_id, pob_index, values.get("CITY", ""), values.get("COUNTRY", "")),
                        "subject_id": subject_id,
                        "place": join_nonempty([values.get("STREET", ""), values.get("CITY", ""), values.get("STATE_PROVINCE", ""), values.get("COUNTRY", "")]),
                        "street": values.get("STREET", ""),
                        "city": values.get("CITY", ""),
                        "state_province": values.get("STATE_PROVINCE", ""),
                        "country_name": values.get("COUNTRY", ""),
                        "note": values.get("NOTE", ""),
                        "source_component_id": f"POB:{pob_index}",
                    },
                )

            for doc_index, doc in enumerate(node.findall("INDIVIDUAL_DOCUMENT"), 1):
                values = {child.tag: clean(child.text or "") for child in doc}
                if not any(values.values()):
                    continue
                extras = join_nonempty(
                    [
                        f"type2={values.get('TYPE_OF_DOCUMENT2', '')}",
                        f"city_of_issue={values.get('CITY_OF_ISSUE', '')}",
                        f"country_of_issue={values.get('COUNTRY_OF_ISSUE', '')}",
                        f"note={values.get('NOTE', '')}",
                    ],
                    sep=" | ",
                )
                builder.add_row(
                    "subject_identifiers",
                    {
                        "identifier_id": stable_id("subject_identifiers", subject_id, doc_index, values.get("NUMBER", ""), values.get("TYPE_OF_DOCUMENT", "")),
                        "subject_id": subject_id,
                        "identifier_type": parse_un_identifier_type(values.get("TYPE_OF_DOCUMENT", "")),
                        "identifier_value": values.get("NUMBER", ""),
                        "issuing_country_name": values.get("ISSUING_COUNTRY", ""),
                        "issued_date": parse_date(values.get("DATE_OF_ISSUE", "")),
                        "additional_information": extras,
                        "source_component_id": f"DOCUMENT:{doc_index}",
                    },
                )

            for nat_index, nationality in enumerate(node.findall("NATIONALITY"), 1):
                value = clean(nationality.findtext("VALUE", ""))
                if not value:
                    continue
                builder.add_row(
                    "subject_nationalities",
                    {
                        "nationality_id": stable_id("subject_nationalities", subject_id, nat_index, value),
                        "subject_id": subject_id,
                        "country_name": value,
                        "nationality_raw": value,
                        "source_component_id": f"NATIONALITY:{nat_index}",
                    },
                )

            program_name = clean(node.findtext("UN_LIST_TYPE", ""))
            if program_name:
                builder.add_row(
                    "subject_programs",
                    {
                        "program_id": stable_id("subject_programs", subject_id, "UN_CONSOLIDATED", program_name),
                        "subject_id": subject_id,
                        "list_family": "UN_CONSOLIDATED",
                        "regime_name": program_name,
                        "program_name": program_name,
                        "source_component_scope": "SUBJECT",
                        "source_component_id": "UN_LIST_TYPE",
                    },
                )

            comments = clean(node.findtext("COMMENTS1", ""))
            if comments:
                builder.add_row(
                    "subject_notes",
                    {
                        "note_id": stable_id("subject_notes", subject_id, "COMMENTS1", comments),
                        "subject_id": subject_id,
                        "note_type": "COMMENTS1",
                        "note_text": comments,
                        "source_component_id": "COMMENTS1",
                    },
                )

            for upd_index, updated in enumerate(node.findall("LAST_DAY_UPDATED"), 1):
                value = clean(updated.findtext("VALUE", "") or updated.text or "")
                if not value:
                    continue
                builder.add_row(
                    "subject_update_events",
                    {
                        "update_id": stable_id("subject_update_events", subject_id, upd_index, value),
                        "subject_id": subject_id,
                        "update_date": parse_date(value),
                        "update_type_raw": "LAST_DAY_UPDATED",
                        "note": value,
                    },
                )


def write_outputs(builder: PipelineBuilder, output_dir: Path) -> None:
    normalize_rows(builder)
    builder.finalize_subjects()
    output_dir.mkdir(parents=True, exist_ok=True)
    for table, columns in TABLES.items():
        write_csv(output_dir / f"{table}.csv", columns, builder.ctx.rows[table])

    write_csv(
        output_dir / "ofac_remark_rule_summary.csv",
        ["rule_name", "count"],
        [{"rule_name": name, "count": str(count)} for name, count in builder.ofac_rule_counts.most_common()],
    )
    write_csv(
        output_dir / "ofac_unmapped_remark_segments.csv",
        ["subject_id", "source_dataset", "segment_index", "segment", "reason"],
        builder.unmapped_ofac_segments,
    )

    per_table = [
        {"table_name": table, "row_count": str(len(builder.ctx.rows[table]))}
        for table in TABLES
    ]
    write_csv(output_dir / "integration_table_counts.csv", ["table_name", "row_count"], per_table)

    source_counter: Counter[Tuple[str, str]] = Counter()
    for row in builder.ctx.rows["sanction_subjects"]:
        source_counter[(row["source_system"], row["source_dataset"])] += 1
    write_csv(
        output_dir / "integration_subject_counts_by_source.csv",
        ["source_system", "source_dataset", "subject_count"],
        [
            {
                "source_system": source_system,
                "source_dataset": source_dataset,
                "subject_count": str(count),
            }
            for (source_system, source_dataset), count in sorted(source_counter.items())
        ],
    )


def normalize_rows(builder: PipelineBuilder) -> None:
    date_value_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for subject in builder.ctx.subjects.values():
        for field, value in list(subject.items()):
            if value == "-0-":
                subject[field] = ""

    for table, rows in builder.ctx.rows.items():
        for row in rows:
            for field, value in list(row.items()):
                if value == "-0-":
                    row[field] = ""

    for row in builder.ctx.rows["subject_vessel_details"]:
        for field in ["tonnage", "grt", "length", "year_built"]:
            value = clean(row.get(field, ""))
            if not value:
                continue
            row[field] = value.replace(",", "")

    merged_vessel_details: Dict[str, Dict[str, str]] = {}
    for row in builder.ctx.rows["subject_vessel_details"]:
        subject_id = row["subject_id"]
        if subject_id not in merged_vessel_details:
            merged_vessel_details[subject_id] = dict(row)
            continue
        current = merged_vessel_details[subject_id]
        for field, value in row.items():
            value = clean(value)
            if field in {"vessel_detail_id", "subject_id", "created_at"} or not value:
                continue
            existing = clean(current.get(field, ""))
            if not existing:
                current[field] = value
            elif existing != value:
                if field == "vessel_type":
                    if value not in existing.split(" | "):
                        current[field] = f"{existing} | {value}"
                elif field in {"flags_previous_raw", "owner_operator_previous_raw", "owner_operator_current_raw", "vessel_owner_raw"}:
                    if value not in existing.split(" | "):
                        current[field] = f"{existing} | {value}"
                else:
                    builder.add_row(
                        "subject_notes",
                        {
                            "note_id": stable_id("subject_notes", subject_id, "VESSEL_DETAIL_CONFLICT", field, existing, value),
                            "subject_id": subject_id,
                            "note_type": "VESSEL_DETAIL_CONFLICT",
                            "note_text": f"{field}: {existing} | {value}",
                            "source_component_id": current.get("vessel_detail_id", ""),
                        },
                    )
    builder.ctx.rows["subject_vessel_details"] = list(merged_vessel_details.values())

    kept_identifiers: List[Dict[str, str]] = []
    for row in builder.ctx.rows["subject_identifiers"]:
        for field in ["issued_date", "valid_from", "valid_to"]:
            value = clean(row.get(field, ""))
            if not value:
                continue
            if date_value_pattern.fullmatch(value):
                continue
            extra = f"{field}_raw={value}"
            existing = clean(row.get("additional_information", ""))
            if not existing:
                row["additional_information"] = extra
            elif extra not in existing.split(" | "):
                row["additional_information"] = f"{existing} | {extra}"
            row[field] = ""
        if not clean(row.get("identifier_value", "")):
            note_text = clean(row.get("additional_information", "")) or f"identifier_type={row.get('identifier_type', '')}"
            builder.add_row(
                "subject_notes",
                {
                    "note_id": stable_id(
                        "subject_notes",
                        row["subject_id"],
                        "IDENTIFIER_WITHOUT_VALUE",
                        note_text,
                        row.get("source_component_id", ""),
                    ),
                    "subject_id": row["subject_id"],
                    "note_type": "IDENTIFIER_WITHOUT_VALUE",
                    "note_text": note_text,
                    "source_component_id": row.get("source_component_id", ""),
                },
            )
            continue
        kept_identifiers.append(row)
    builder.ctx.rows["subject_identifiers"] = kept_identifiers

    for row in builder.ctx.rows["subject_names"]:
        if not clean(row.get("full_name", "")) and clean(row.get("non_latin_name", "")):
            row["full_name"] = clean(row["non_latin_name"])

    fax_notes: List[Dict[str, str]] = []
    kept_contacts: List[Dict[str, str]] = []
    for row in builder.ctx.rows["subject_contacts"]:
        contact_type = clean(row.get("contact_type", ""))
        if contact_type == "FAX":
            fax_notes.append(
                {
                    "note_id": stable_id("subject_notes", row["subject_id"], "CONTACT_FAX", row.get("contact_value", "")),
                    "subject_id": row["subject_id"],
                    "note_type": "CONTACT_FAX",
                    "note_text": row.get("contact_value", ""),
                    "source_component_id": row.get("contact_id", ""),
                    "created_at": builder.created_at,
                }
            )
            continue
        kept_contacts.append(row)
    builder.ctx.rows["subject_contacts"] = kept_contacts
    for note in fax_notes:
        builder.add_row("subject_notes", note)

    for row in builder.ctx.rows["subject_notes"]:
        if row.get("note_type") == "REMARKS_UNPARSED_SEGMENT":
            row["note_type"] = "REMARKS_UNPARSED_REMAINDER"

    existing_note_keys = {
        (row["subject_id"], row["note_type"], row["note_text"])
        for row in builder.ctx.rows["subject_notes"]
    }
    for measure in builder.ctx.rows["subject_measures"]:
        if measure.get("measure_type") != "ADDITIONAL_SANCTIONS_INFORMATION":
            continue
        key = (measure["subject_id"], "ADDITIONAL_SANCTIONS_INFORMATION", measure.get("measure_raw_text", ""))
        if key in existing_note_keys:
            continue
        builder.add_row(
            "subject_notes",
            {
                "note_id": stable_id("subject_notes", measure["subject_id"], *key[1:]),
                "subject_id": measure["subject_id"],
                "note_type": "ADDITIONAL_SANCTIONS_INFORMATION",
                "note_text": measure.get("measure_raw_text", ""),
                "source_component_id": measure.get("measure_id", ""),
            },
        )

    dedupe_specs = {
        "subject_names": lambda r: (r["subject_id"], clean(r.get("full_name", "")), r.get("name_type", "")),
        "subject_addresses": lambda r: (r["subject_id"], clean(r.get("address_full_raw", "")), clean(r.get("country_name", ""))),
        "subject_identifiers": lambda r: (r["subject_id"], r.get("identifier_type", ""), clean(r.get("identifier_value", ""))),
        "subject_birth_dates": lambda r: (
            r["subject_id"],
            r.get("birth_date", ""),
            r.get("year", ""),
            r.get("year_from", ""),
            r.get("year_to", ""),
            r.get("date_type_raw", ""),
        ),
        "subject_birth_places": lambda r: (
            r["subject_id"],
            clean(r.get("place", "")),
            clean(r.get("city", "")),
            clean(r.get("country_name", "")),
        ),
        "subject_nationalities": lambda r: (
            r["subject_id"],
            clean(r.get("country_code", "")),
            clean(r.get("country_name", "")),
            clean(r.get("nationality_raw", "")),
        ),
        "subject_contacts": lambda r: (r["subject_id"], r.get("contact_type", ""), clean(r.get("contact_value", ""))),
        "subject_relationships": lambda r: (r["subject_id"], r.get("relationship_type", ""), clean(r.get("related_name", ""))),
        "subject_vessel_details": lambda r: (
            r["subject_id"],
            clean(r.get("imo_number", "")),
            clean(r.get("call_sign", "")),
            clean(r.get("vessel_type", "")),
            clean(r.get("flag_current", "")),
        ),
        "subject_programs": lambda r: (
            r["subject_id"],
            r.get("list_family", ""),
            clean(r.get("regime_name", "")),
            clean(r.get("program_name", "")),
            r.get("source_component_scope", ""),
        ),
        "subject_regulations": lambda r: (
            r["subject_id"],
            r.get("regulation_scope", ""),
            clean(r.get("regulation_type", "")),
            clean(r.get("organisation_type", "")),
            r.get("publication_date", ""),
            r.get("entry_into_force_date", ""),
            clean(r.get("number_title", "")),
            clean(r.get("publication_url", "")),
            clean(r.get("regulation_language", "")),
        ),
        "subject_measures": lambda r: (r["subject_id"], r.get("measure_type", ""), clean(r.get("measure_raw_text", ""))),
        "subject_notes": lambda r: (r["subject_id"], r.get("note_type", ""), clean(r.get("note_text", ""))),
    }
    appendable_fields = {"note", "additional_information"}
    for table, key_fn in dedupe_specs.items():
        merged: Dict[tuple, Dict[str, str]] = {}
        for row in builder.ctx.rows[table]:
            key = key_fn(row)
            if key not in merged:
                merged[key] = dict(row)
                continue
            current = merged[key]
            for field, value in row.items():
                value = clean(value) if isinstance(value, str) else value
                if not value:
                    continue
                if field in appendable_fields:
                    existing = clean(current.get(field, ""))
                    if not existing:
                        current[field] = value
                    elif value not in existing.split(" | "):
                        current[field] = f"{existing} | {value}"
                elif not clean(current.get(field, "")):
                    current[field] = value
        builder.ctx.rows[table] = list(merged.values())

    for row in builder.ctx.rows["subject_names"]:
        row["subject_name_id"] = stable_id(
            "subject_names",
            row["subject_id"],
            clean(row.get("full_name", "")) or clean(row.get("non_latin_name", "")),
            row.get("name_type", ""),
            row.get("is_primary", ""),
        )

    for row in builder.ctx.rows["subject_addresses"]:
        row["address_id"] = stable_id(
            "subject_addresses",
            row["subject_id"],
            clean(row.get("address_full_raw", "")),
            clean(row.get("country_name", "")),
        )

    for row in builder.ctx.rows["subject_identifiers"]:
        row["identifier_id"] = stable_id(
            "subject_identifiers",
            row["subject_id"],
            row.get("identifier_type", ""),
            clean(row.get("identifier_value", "")),
        )

    for row in builder.ctx.rows["subject_birth_dates"]:
        row["birth_date_id"] = stable_id(
            "subject_birth_dates",
            row["subject_id"],
            row.get("birth_date", ""),
            row.get("year", ""),
            row.get("year_from", ""),
            row.get("year_to", ""),
            row.get("date_type_raw", ""),
        )

    for row in builder.ctx.rows["subject_birth_places"]:
        row["birth_place_id"] = stable_id(
            "subject_birth_places",
            row["subject_id"],
            clean(row.get("place", "")),
            clean(row.get("city", "")),
            clean(row.get("country_name", "")),
        )

    for row in builder.ctx.rows["subject_nationalities"]:
        row["nationality_id"] = stable_id(
            "subject_nationalities",
            row["subject_id"],
            clean(row.get("country_code", "")),
            clean(row.get("country_name", "")),
            clean(row.get("nationality_raw", "")),
        )

    for row in builder.ctx.rows["subject_contacts"]:
        row["contact_id"] = stable_id(
            "subject_contacts",
            row["subject_id"],
            row.get("contact_type", ""),
            clean(row.get("contact_value", "")),
        )

    for row in builder.ctx.rows["subject_relationships"]:
        row["relationship_id"] = stable_id(
            "subject_relationships",
            row["subject_id"],
            row.get("relationship_type", ""),
            clean(row.get("related_name", "")),
        )

    for row in builder.ctx.rows["subject_vessel_details"]:
        row["vessel_detail_id"] = stable_id(
            "subject_vessel_details",
            row["subject_id"],
            clean(row.get("imo_number", "")),
            clean(row.get("call_sign", "")),
            clean(row.get("vessel_type", "")),
            clean(row.get("flag_current", "")),
        )

    for row in builder.ctx.rows["subject_programs"]:
        row["program_id"] = stable_id(
            "subject_programs",
            row["subject_id"],
            row.get("list_family", ""),
            clean(row.get("regime_name", "")),
            clean(row.get("program_name", "")),
            row.get("source_component_scope", ""),
        )

    for row in builder.ctx.rows["subject_regulations"]:
        row["regulation_id"] = stable_id(
            "subject_regulations",
            row["subject_id"],
            row.get("regulation_scope", ""),
            clean(row.get("regulation_type", "")),
            clean(row.get("organisation_type", "")),
            row.get("publication_date", ""),
            row.get("entry_into_force_date", ""),
            clean(row.get("number_title", "")),
            clean(row.get("publication_url", "")),
            clean(row.get("regulation_language", "")),
        )

    for row in builder.ctx.rows["subject_measures"]:
        row["measure_id"] = stable_id(
            "subject_measures",
            row["subject_id"],
            row.get("measure_type", ""),
            clean(row.get("measure_raw_text", "")),
        )

    for row in builder.ctx.rows["subject_notes"]:
        row["note_id"] = stable_id(
            "subject_notes",
            row["subject_id"],
            row.get("note_type", ""),
            clean(row.get("note_text", "")),
            clean(row.get("source_component_id", "")),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eu", default="EU_20260410-FULL-1_1.csv", type=Path)
    parser.add_argument("--un", dest="un_xml", default="UN_consolidatedLegacyByPRN.xml", type=Path)
    parser.add_argument("--uk", default="UK-Sanctions-List.csv", type=Path)
    parser.add_argument("--ofac-dir", default=Path("ofac"), type=Path)
    parser.add_argument("--output-dir", default=Path("integrated_schema_batch"), type=Path)
    parser.add_argument("--skip-eu", action="store_true")
    parser.add_argument("--skip-un", action="store_true")
    parser.add_argument("--skip-uk", action="store_true")
    parser.add_argument(
        "--created-at",
        default=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    args = parser.parse_args()

    builder = PipelineBuilder(args.created_at)

    print("stage=ofac_sdn", flush=True)
    parse_ofac_dataset(
        builder,
        "OFAC_SDN",
        args.ofac_dir / "sdn.csv",
        args.ofac_dir / "alt.csv",
        args.ofac_dir / "add.csv",
        args.ofac_dir / "sdn_comments.csv",
    )
    print("stage=ofac_cons", flush=True)
    parse_ofac_dataset(
        builder,
        "OFAC_CONS",
        args.ofac_dir / "cons_prim.csv",
        args.ofac_dir / "cons_alt.csv",
        args.ofac_dir / "cons_add.csv",
        args.ofac_dir / "cons_comments.csv",
    )
    if not args.skip_eu:
        print("stage=eu", flush=True)
        parse_eu(builder, args.eu)
    if not args.skip_un:
        print("stage=un", flush=True)
        parse_un(builder, args.un_xml)
    if not args.skip_uk:
        print("stage=uk", flush=True)
        parse_uk(builder, args.uk)
    print("stage=write_outputs", flush=True)
    write_outputs(builder, args.output_dir)

    builder.finalize_subjects()
    print(f"output_dir={args.output_dir}")
    print(f"subjects={len(builder.ctx.rows['sanction_subjects'])}")
    print(f"ofac_rule_hits={sum(builder.ofac_rule_counts.values())}")
    print(f"ofac_unmapped_segments={len(builder.unmapped_ofac_segments)}")
    for table in ["subject_names", "subject_addresses", "subject_identifiers", "subject_notes"]:
        print(f"{table}={len(builder.ctx.rows[table])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
