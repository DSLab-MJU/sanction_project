#!/usr/bin/env python3
"""
Map OFAC SDN remarks into the 16 ERD tables using explicit remark prefixes only.

Input:
  sdn.csv without a header, in OFAC SDN layout:
    ent_num, SDN_Name, SDN_Type, Program, Title,
    Call_Sign, Vess_type, Tonnage, GRT, Vess_flag, Vess_owner, Remarks

Output:
  One CSV per ERD table, plus:
    remark_prefix_mapping_summary.csv
    unmapped_remark_segments.csv

Design rule:
  This parser only maps segments whose meaning is declared by an explicit
  prefix/label, such as "DOB", "POB", "Passport", "Linked To:",
  "Organization Type:", etc. Free-text role sentences such as "General" or
  "Director of ..." are intentionally not mapped and remain in notes/unmapped.
"""

from __future__ import annotations

import argparse
import csv
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Match, Optional, Tuple


TABLES: Dict[str, List[str]] = {
    "sanction_subjects": [
        "subject_id",
        "source_system",
        "source_dataset",
        "subject_type",
        "subject_type_raw",
        "subject_type_code_raw",
        "primary_name",
        "title",
        "gender",
        "function_role",
        "designation_date",
        "designation_details_raw",
        "designation_source_raw",
        "entity_subtype_raw",
        "is_active",
        "created_at",
        "updated_at",
    ],
    "subject_names": [
        "subject_name_id",
        "subject_id",
        "full_name",
        "name_part_1",
        "name_part_2",
        "name_part_3",
        "name_part_4",
        "name_part_5",
        "name_part_6",
        "name_type",
        "alias_strength",
        "name_quality",
        "is_primary",
        "non_latin_name",
        "non_latin_script_type",
        "non_latin_language",
        "language_code",
        "note",
        "source_component_id",
        "created_at",
    ],
    "subject_addresses": [
        "address_id",
        "subject_id",
        "address_full_raw",
        "address_line_1",
        "address_line_2",
        "address_line_3",
        "address_line_4",
        "address_line_5",
        "address_line_6",
        "street",
        "po_box",
        "city",
        "state_province",
        "region",
        "place",
        "postal_code",
        "country_code",
        "country_name",
        "as_at_listing_time",
        "contact_info",
        "note",
        "source_component_id",
        "created_at",
    ],
    "subject_identifiers": [
        "identifier_id",
        "subject_id",
        "identifier_type",
        "identifier_value",
        "identifier_value_latin",
        "name_on_document",
        "issued_by",
        "issuing_country_code",
        "issuing_country_name",
        "issued_date",
        "valid_from",
        "valid_to",
        "is_diplomatic",
        "is_known_expired",
        "is_known_false",
        "is_reported_lost",
        "is_revoked_by_issuer",
        "additional_information",
        "source_component_id",
        "created_at",
    ],
    "subject_birth_dates": [
        "birth_date_id",
        "subject_id",
        "birth_date",
        "day",
        "month",
        "year",
        "year_from",
        "year_to",
        "circa_flag",
        "calendar_type",
        "date_type_raw",
        "is_incomplete",
        "note",
        "source_component_id",
        "created_at",
    ],
    "subject_birth_places": [
        "birth_place_id",
        "subject_id",
        "place",
        "street",
        "city",
        "state_province",
        "region",
        "postal_code",
        "country_code",
        "country_name",
        "note",
        "source_component_id",
        "created_at",
    ],
    "subject_nationalities": [
        "nationality_id",
        "subject_id",
        "country_code",
        "country_name",
        "region",
        "nationality_raw",
        "note",
        "source_component_id",
        "created_at",
    ],
    "subject_contacts": [
        "contact_id",
        "subject_id",
        "contact_type",
        "contact_value",
        "note",
        "created_at",
    ],
    "subject_relationships": [
        "relationship_id",
        "subject_id",
        "relationship_type",
        "related_name",
        "note",
        "source_component_id",
        "created_at",
    ],
    "subject_vessel_details": [
        "vessel_detail_id",
        "subject_id",
        "call_sign",
        "imo_number",
        "vessel_type",
        "tonnage",
        "grt",
        "length",
        "year_built",
        "flag_current",
        "flags_previous_raw",
        "hull_id",
        "owner_operator_current_raw",
        "owner_operator_previous_raw",
        "vessel_owner_raw",
        "created_at",
    ],
    "subject_programs": [
        "program_id",
        "subject_id",
        "list_family",
        "regime_name",
        "program_name",
        "source_component_scope",
        "source_component_id",
        "note",
        "created_at",
    ],
    "subject_regulations": [
        "regulation_id",
        "subject_id",
        "regulation_scope",
        "regulation_type",
        "organisation_type",
        "publication_date",
        "entry_into_force_date",
        "number_title",
        "publication_url",
        "regulation_language",
        "note",
        "source_component_id",
        "created_at",
    ],
    "subject_measures": [
        "measure_id",
        "subject_id",
        "measure_type",
        "measure_raw_text",
        "severity_hint",
        "created_at",
    ],
    "subject_notes": [
        "note_id",
        "subject_id",
        "note_type",
        "note_text",
        "source_component_id",
        "created_at",
    ],
    "subject_source_records": [
        "source_record_id",
        "subject_id",
        "source_system",
        "source_dataset",
        "source_primary_id",
        "source_secondary_id",
        "source_tertiary_id",
        "source_component_type",
        "source_component_id",
        "file_generation_date",
        "report_date",
        "version_num",
        "list_type_raw",
        "sort_key",
        "sort_key_last_mod",
        "created_at",
    ],
    "subject_update_events": [
        "update_id",
        "subject_id",
        "update_date",
        "update_type_raw",
        "note",
        "created_at",
    ],
}


MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


COUNTRY_HINTS = {
    "Afghanistan",
    "Argentina",
    "Belarus",
    "Burma",
    "China",
    "Colombia",
    "Cuba",
    "Egypt",
    "Germany",
    "Guatemala",
    "India",
    "Indonesia",
    "Iran",
    "Iraq",
    "Italy",
    "Korea, North",
    "Lebanon",
    "Libya",
    "Mexico",
    "Nicaragua",
    "Pakistan",
    "Russia",
    "Saudi Arabia",
    "Somalia",
    "Syria",
    "Turkey",
    "Ukraine",
    "United Arab Emirates",
    "United Kingdom",
    "United States",
    "Venezuela",
    "Yemen",
}


def clean(value: str) -> str:
    return value.strip().strip('"').strip()


def clean_trailing(value: str) -> str:
    value = clean(value)
    return value[:-1].strip() if value.endswith(".") else value


def nullish(value: str) -> bool:
    return not value.strip() or value.strip() == "-0-"


def stable_id(*parts: object) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "ofac-sdn|" + "|".join(map(str, parts))))


def blank_row(table: str) -> Dict[str, str]:
    return {column: "" for column in TABLES[table]}


def normalize_subject_type(raw_value: str) -> str:
    raw = raw_value.strip().lower()
    if raw == "individual":
        return "INDIVIDUAL"
    if raw == "vessel":
        return "VESSEL"
    if raw == "aircraft":
        return "AIRCRAFT"
    return "ENTITY"


def split_programs(program: str) -> List[str]:
    if nullish(program):
        return []
    return [part.strip() for part in re.split(r";|\|", program) if part.strip()]


def split_remark_segments(remark: str) -> List[str]:
    if nullish(remark):
        return []
    # OFAC SDN remarks use semicolon as the practical segment separator.
    # We deliberately do not track apostrophes as quotes because values such as
    # "Manufacturer's" are common and would break quote-aware splitting.
    return [segment.strip() for segment in remark.split(";") if segment.strip()]


def parse_day_mon_year(value: str) -> Optional[str]:
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", value.strip())
    if not match:
        return None
    day = int(match.group(1))
    month = MONTHS.get(match.group(2).lower())
    year = int(match.group(3))
    if not month:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_month_year(value: str) -> Tuple[str, str]:
    match = re.fullmatch(r"([A-Za-z]{3})\s+(\d{4})", value.strip())
    if not match:
        return "", ""
    month = MONTHS.get(match.group(1).lower())
    return (str(month) if month else "", match.group(2))


def parse_year(value: str) -> str:
    match = re.fullmatch(r"\d{4}", value.strip())
    return match.group(0) if match else ""


def parse_birth_date_value(value: str) -> Dict[str, str]:
    value = clean_trailing(value)
    result = {
        "birth_date": "",
        "day": "",
        "month": "",
        "year": "",
        "year_from": "",
        "year_to": "",
        "circa_flag": "0",
        "is_incomplete": "0",
    }

    if re.match(r"^circa\b", value, re.I):
        result["circa_flag"] = "1"
        result["is_incomplete"] = "1"
        value = re.sub(r"^circa\s+", "", value, flags=re.I).strip()

    if " to " in value:
        left, right = [part.strip() for part in value.split(" to ", 1)]
        left_year = re.search(r"\b(\d{4})\b", left)
        right_year = re.search(r"\b(\d{4})\b", right)
        result["year_from"] = left_year.group(1) if left_year else ""
        result["year_to"] = right_year.group(1) if right_year else ""
        result["is_incomplete"] = "1"
        return result

    full_date = parse_day_mon_year(value)
    if full_date:
        result["birth_date"] = full_date
        result["day"] = str(int(value.split()[0]))
        result["month"] = str(MONTHS[value.split()[1].lower()])
        result["year"] = value.split()[2]
        return result

    month, year = parse_month_year(value)
    if month and year:
        result["month"] = month
        result["year"] = year
        result["is_incomplete"] = "1"
        return result

    year = parse_year(value)
    if year:
        result["year"] = year
        result["is_incomplete"] = "1"

    return result


def extract_parenthetical_country(value: str) -> Tuple[str, str]:
    """Return value_without_last_parenthetical, country_or_note."""
    match = re.search(r"\s+\(([^()]*)\)\.?$", value.strip())
    if not match:
        return value.strip(), ""
    return value[: match.start()].strip(), match.group(1).strip()


def parse_issued_and_valid_to(value: str) -> Tuple[str, str, str]:
    issued_date = ""
    valid_to = ""
    rest = value

    issued_match = re.search(
        r"\bissued\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", rest, flags=re.I
    )
    if issued_match:
        issued_date = parse_day_mon_year(issued_match.group(1)) or issued_match.group(1)
        rest = (rest[: issued_match.start()] + rest[issued_match.end() :]).strip()

    expires_match = re.search(
        r"\bexpires?\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4}|[A-Za-z]{3}\s+\d{4}|\d{4})",
        rest,
        flags=re.I,
    )
    if expires_match:
        valid_to = parse_day_mon_year(expires_match.group(1)) or expires_match.group(1)
        rest = (rest[: expires_match.start()] + rest[expires_match.end() :]).strip()

    return clean_trailing(rest), issued_date, valid_to


def parse_identifier_value(value: str) -> Tuple[str, str, str, str]:
    """Return identifier_value, issuing_country_name, issued_date, valid_to."""
    value, issued_date, valid_to = parse_issued_and_valid_to(value)
    value, country = extract_parenthetical_country(value)
    return clean_trailing(value), country, issued_date, valid_to


def parse_place(value: str) -> Tuple[str, str, str]:
    """Return place, city, country_name using conservative comma parsing."""
    place = clean_trailing(value)
    parts = [part.strip() for part in place.split(",") if part.strip()]
    if len(parts) >= 2 and parts[-1] in COUNTRY_HINTS:
        return place, parts[0], parts[-1]
    if len(parts) == 1 and parts[0] in COUNTRY_HINTS:
        return place, "", parts[0]
    return place, "", ""


class Context:
    def __init__(self, created_at: str) -> None:
        self.created_at = created_at
        self.rows: Dict[str, List[Dict[str, str]]] = {table: [] for table in TABLES}
        self.subjects: Dict[str, Dict[str, str]] = {}
        self.rule_counts: Counter[str] = Counter()
        self.unmapped: List[Dict[str, str]] = []

    def add(self, table: str, row: Dict[str, str]) -> None:
        self.rows[table].append(row)

    def subject(self, subject_id: str) -> Dict[str, str]:
        return self.subjects[subject_id]

    def append_subject_field(self, subject_id: str, field: str, value: str) -> None:
        value = clean_trailing(value)
        if not value:
            return
        subject = self.subject(subject_id)
        existing = subject.get(field, "")
        values = [part.strip() for part in existing.split(" | ") if part.strip()]
        if value not in values:
            values.append(value)
        subject[field] = " | ".join(values)


Handler = Callable[[Context, str, int, str, Match[str]], None]


class Rule:
    def __init__(self, name: str, pattern: str, handler: Handler) -> None:
        self.name = name
        self.regex = re.compile(pattern, re.I)
        self.handler = handler


def source_component(segment_index: int) -> str:
    return f"REMARKS:{segment_index}"


def add_note(
    ctx: Context,
    subject_id: str,
    segment_index: int,
    note_type: str,
    note_text: str,
) -> None:
    row = blank_row("subject_notes")
    row.update(
        {
            "note_id": stable_id("subject_notes", subject_id, segment_index, note_type, note_text),
            "subject_id": subject_id,
            "note_type": note_type,
            "note_text": note_text,
            "source_component_id": source_component(segment_index),
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_notes", row)


def add_measure(
    ctx: Context,
    subject_id: str,
    measure_type: str,
    raw_text: str,
    severity_hint: str = "",
) -> None:
    row = blank_row("subject_measures")
    row.update(
        {
            "measure_id": stable_id("subject_measures", subject_id, measure_type, raw_text),
            "subject_id": subject_id,
            "measure_type": measure_type,
            "measure_raw_text": raw_text,
            "severity_hint": severity_hint,
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_measures", row)
    ctx.append_subject_field(subject_id, "designation_details_raw", raw_text)


def handle_alias(name_type: str) -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        value = clean_trailing(match.group(1))
        quoted = re.fullmatch(r"'(.*)'", value)
        if quoted:
            value = quoted.group(1).strip()
        row = blank_row("subject_names")
        row.update(
            {
                "subject_name_id": stable_id("subject_names", subject_id, name_type, value),
                "subject_id": subject_id,
                "full_name": value,
                "name_type": name_type,
                "is_primary": "0",
                "note": "PARSED_FROM_REMARKS",
                "source_component_id": source_component(segment_index),
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_names", row)

    return handler


def handle_gender(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
    ctx.append_subject_field(subject_id, "gender", match.group(1))


def handle_entity_subtype(label: str) -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        ctx.append_subject_field(subject_id, "entity_subtype_raw", f"{label}: {match.group(1)}")

    return handler


def handle_listing_date(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
    date_value = parse_day_mon_year(match.group(2)) or clean_trailing(match.group(2))
    subject = ctx.subject(subject_id)
    if not subject.get("designation_date") and date_value:
        subject["designation_date"] = date_value
    ctx.append_subject_field(subject_id, "designation_details_raw", segment)


def handle_measure(measure_type: str, severity_hint: str = "") -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        add_measure(ctx, subject_id, measure_type, segment, severity_hint)

    return handler


def handle_birth_date(date_type_raw: str) -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        value = match.group(1)
        parsed = parse_birth_date_value(value)
        row = blank_row("subject_birth_dates")
        row.update(
            {
                "birth_date_id": stable_id("subject_birth_dates", subject_id, segment_index, segment),
                "subject_id": subject_id,
                "birth_date": parsed["birth_date"],
                "day": parsed["day"],
                "month": parsed["month"],
                "year": parsed["year"],
                "year_from": parsed["year_from"],
                "year_to": parsed["year_to"],
                "circa_flag": parsed["circa_flag"],
                "date_type_raw": date_type_raw,
                "is_incomplete": parsed["is_incomplete"],
                "note": segment,
                "source_component_id": source_component(segment_index),
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_birth_dates", row)

    return handler


def handle_birth_place(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
    place, city, country = parse_place(match.group(1))
    row = blank_row("subject_birth_places")
    row.update(
        {
            "birth_place_id": stable_id("subject_birth_places", subject_id, segment_index, place),
            "subject_id": subject_id,
            "place": place,
            "city": city,
            "country_name": country,
            "note": segment,
            "source_component_id": source_component(segment_index),
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_birth_places", row)


def handle_nationality(note: str = "") -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        value = clean_trailing(match.group(1))
        row = blank_row("subject_nationalities")
        row.update(
            {
                "nationality_id": stable_id("subject_nationalities", subject_id, segment_index, value),
                "subject_id": subject_id,
                "country_name": value if value in COUNTRY_HINTS else "",
                "nationality_raw": value,
                "note": note,
                "source_component_id": source_component(segment_index),
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_nationalities", row)

    return handler


def handle_identifier(identifier_type: str, additional_prefix: str = "") -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        value, country, issued_date, valid_to = parse_identifier_value(match.group(1))
        row = blank_row("subject_identifiers")
        additional = additional_prefix
        if country and country not in COUNTRY_HINTS:
            additional = " | ".join(part for part in [additional, f"parenthetical={country}"] if part)
            country = ""
        row.update(
            {
                "identifier_id": stable_id("subject_identifiers", subject_id, segment_index, identifier_type, value),
                "subject_id": subject_id,
                "identifier_type": identifier_type,
                "identifier_value": value,
                "issuing_country_name": country,
                "issued_date": issued_date,
                "valid_to": valid_to,
                "additional_information": additional,
                "source_component_id": source_component(segment_index),
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_identifiers", row)

    return handler


def handle_identifier_groups(
    identifier_type: str,
    value_group: int,
    raw_type_group: Optional[int] = None,
    additional_prefix: str = "",
) -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        value, country, issued_date, valid_to = parse_identifier_value(match.group(value_group))
        additional_parts = []
        if additional_prefix:
            additional_parts.append(additional_prefix)
        if raw_type_group is not None:
            additional_parts.append(f"raw_type={match.group(raw_type_group)}")
        if country and country not in COUNTRY_HINTS:
            additional_parts.append(f"parenthetical={country}")
            country = ""
        row = blank_row("subject_identifiers")
        row.update(
            {
                "identifier_id": stable_id("subject_identifiers", subject_id, segment_index, identifier_type, value),
                "subject_id": subject_id,
                "identifier_type": identifier_type,
                "identifier_value": value,
                "issuing_country_name": country,
                "issued_date": issued_date,
                "valid_to": valid_to,
                "additional_information": " | ".join(additional_parts),
                "source_component_id": source_component(segment_index),
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_identifiers", row)

    return handler


def handle_digital_currency(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
    chain = clean(match.group(1))
    address = clean_trailing(match.group(2))
    row = blank_row("subject_identifiers")
    row.update(
        {
            "identifier_id": stable_id("subject_identifiers", subject_id, segment_index, "DIGITAL_CURRENCY_ADDRESS", address),
            "subject_id": subject_id,
            "identifier_type": "DIGITAL_CURRENCY_ADDRESS",
            "identifier_value": address,
            "additional_information": f"network_or_asset={chain}" if chain else "",
            "source_component_id": source_component(segment_index),
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_identifiers", row)


def handle_contact(contact_type: str) -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        value = clean_trailing(match.group(1))
        row = blank_row("subject_contacts")
        row.update(
            {
                "contact_id": stable_id("subject_contacts", subject_id, segment_index, contact_type, value),
                "subject_id": subject_id,
                "contact_type": contact_type,
                "contact_value": value,
                "note": "PARSED_FROM_REMARKS",
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_contacts", row)

    return handler


def handle_relationship(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
    related_name = clean_trailing(match.group(1))
    row = blank_row("subject_relationships")
    row.update(
        {
            "relationship_id": stable_id("subject_relationships", subject_id, segment_index, related_name),
            "subject_id": subject_id,
            "relationship_type": "LINKED_TO",
            "related_name": related_name,
            "note": segment,
            "source_component_id": source_component(segment_index),
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_relationships", row)


def add_or_update_vessel(ctx: Context, subject_id: str, field: str, value: str) -> None:
    row = blank_row("subject_vessel_details")
    row.update(
        {
            "vessel_detail_id": stable_id("subject_vessel_details", subject_id),
            "subject_id": subject_id,
            "created_at": ctx.created_at,
        }
    )
    for existing in ctx.rows["subject_vessel_details"]:
        if existing["subject_id"] == subject_id and existing["vessel_detail_id"] == row["vessel_detail_id"]:
            existing[field] = clean_trailing(value)
            return
    row[field] = clean_trailing(value)
    ctx.add("subject_vessel_details", row)


def handle_vessel(field: str) -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        value = match.group(1)
        add_or_update_vessel(ctx, subject_id, field, value)
        if field == "imo_number":
            handle_identifier("IMO_NUMBER")(ctx, subject_id, segment_index, segment, match)

    return handler


def handle_vessel_flag(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
    prefix = match.group(1).lower()
    value = match.group(2)
    field = "flags_previous_raw" if "former" in prefix else "flag_current"
    add_or_update_vessel(ctx, subject_id, field, value)


def handle_note(note_type: str) -> Handler:
    def handler(ctx: Context, subject_id: str, segment_index: int, segment: str, match: Match[str]) -> None:
        add_note(ctx, subject_id, segment_index, note_type, segment)

    return handler


RULES: List[Rule] = [
    Rule("name_aka", r"^(?:alt\.\s*)?a\.k\.a\.\s+(.+)$", handle_alias("AKA")),
    Rule("name_fka", r"^(?:alt\.\s*)?f\.k\.a\.\s+(.+)$", handle_alias("FKA")),
    Rule("name_nka", r"^(?:alt\.\s*)?n\.k\.a\.\s+(.+)$", handle_alias("NKA")),
    Rule("dob_alt", r"^alt\.\s+DOB\s+(.+)$", handle_birth_date("ALT_DOB")),
    Rule("dob", r"^DOB\s+(.+)$", handle_birth_date("PRIMARY_DOB")),
    Rule("pob_alt", r"^alt\.\s+POB\s+(.+)$", handle_birth_place),
    Rule("pob", r"^POB\s+(.+)$", handle_birth_place),
    Rule("gender", r"^Gender\s+(.+?)\.?$", handle_gender),
    Rule("nationality_alt", r"^alt\.\s+nationality\s+(.+)$", handle_nationality("ALT_NATIONALITY")),
    Rule("nationality", r"^nationality\s+(.+)$", handle_nationality()),
    Rule("citizen_alt", r"^alt\.\s+citizen\s+(.+)$", handle_nationality("ALT_CITIZEN")),
    Rule("citizen", r"^citizen\s+(.+)$", handle_nationality("CITIZEN")),
    Rule("organization_type_alt", r"^alt\.\s+Organization Type:\s*(.+)$", handle_entity_subtype("alt. Organization Type")),
    Rule("organization_type", r"^Organization Type:\s*(.+)$", handle_entity_subtype("Organization Type")),
    Rule("target_type_alt", r"^alt\.\s+Target Type\s+(.+)$", handle_entity_subtype("alt. Target Type")),
    Rule("target_type", r"^Target Type\s+(.+)$", handle_entity_subtype("Target Type")),
    Rule("listing_date", r"^Listing Date \(([^)]+)\):\s*(.+)$", handle_listing_date),
    Rule("effective_date", r"^Effective Date \(([^)]+)\):\s*(.+)$", handle_measure("EFFECTIVE_DATE")),
    Rule("secondary_sanctions_risk_alt", r"^alt\.\s+Secondary sanctions risk:\s*(.+)$", handle_measure("SECONDARY_SANCTIONS_RISK", "ALT")),
    Rule("secondary_sanctions_risk", r"^Secondary sanctions risk:\s*(.+)$", handle_measure("SECONDARY_SANCTIONS_RISK")),
    Rule("additional_sanctions_info_alt", r"^alt\.\s+Additional Sanctions Information\s*-\s*(.+)$", handle_measure("ADDITIONAL_SANCTIONS_INFORMATION", "ALT")),
    Rule("additional_sanctions_info", r"^Additional Sanctions Information\s*-\s*(.+)$", handle_measure("ADDITIONAL_SANCTIONS_INFORMATION")),
    Rule("transactions_prohibited", r"^(Transactions Prohibited For Persons Owned or Controlled By U\.S\. Financial Institutions:.*)$", handle_measure("TRANSACTIONS_PROHIBITED")),
    Rule("executive_order_info_alt", r"^(alt\.\s+Executive Order .*)$", handle_measure("EXECUTIVE_ORDER_INFORMATION", "ALT")),
    Rule("executive_order_info", r"^(Executive Order .*)$", handle_measure("EXECUTIVE_ORDER_INFORMATION")),
    Rule("caatsa_info_alt", r"^(alt\.\s+CAATSA Section 235 Information:.*)$", handle_measure("CAATSA_SECTION_235_INFORMATION", "ALT")),
    Rule("caatsa_info", r"^(CAATSA Section 235 Information:.*)$", handle_measure("CAATSA_SECTION_235_INFORMATION")),
    Rule("paipa_info_alt", r"^(alt\.\s+PAIPA Section 2 Information:.*)$", handle_measure("PAIPA_SECTION_2_INFORMATION", "ALT")),
    Rule("paipa_info", r"^(PAIPA Section 2 Information:.*)$", handle_measure("PAIPA_SECTION_2_INFORMATION")),
    Rule("ifca_determination", r"^(IFCA Determination\s*-.*)$", handle_measure("IFCA_DETERMINATION")),
    Rule("directive_url", r"^(For more information.*)$", handle_note("DIRECTIVE_INFORMATION_URL")),
    Rule("passport_alt", r"^alt\.\s+Passport\s+(.+)$", handle_identifier("PASSPORT", "ALT_PASSPORT")),
    Rule("passport", r"^Passport\s+(.+)$", handle_identifier("PASSPORT")),
    Rule("passport_issued_country_first", r"^[A-Z.]+ Passport issued\s+(.+)$", handle_identifier("PASSPORT")),
    Rule("ssn_alt", r"^alt\.\s+SSN\s+(.+)$", handle_identifier("SSN", "ALT_SSN")),
    Rule("ssn", r"^SSN\s+(.+)$", handle_identifier("SSN")),
    Rule("national_id_alt", r"^alt\.\s+(National ID No\.|Kenyan ID No\.|D\.N\.I\.|Credencial electoral|Public Security and Immigration No\.)[: ]+(.+)$", handle_identifier_groups("NATIONAL_ID", 2, 1, "ALT_NATIONAL_ID")),
    Rule("national_id", r"^(National ID No\.|Kenyan ID No\.|D\.N\.I\.|Credencial electoral|Public Security and Immigration No\.)[: ]+(.+)$", handle_identifier_groups("NATIONAL_ID", 2, 1)),
    Rule("cedula_alt", r"^alt\.\s+Cedula No\.\s+(.+)$", handle_identifier("CEDULA", "ALT_CEDULA")),
    Rule("cedula", r"^Cedula No\.\s+(.+)$", handle_identifier("CEDULA")),
    Rule("tax_local_alt", r"^alt\.\s+(Tax ID No\.|US FEIN|C\.U\.I\.T\.|C\.U\.R\.P\.|R\.F\.C\.|NIT #|Numero Unico de Identificacao Tributaria \(NUIT\)|Italian Fiscal Code|V\.A\.T\. Number)[: ]+(.+)$", handle_identifier_groups("TAX_ID", 2, 1, "ALT_TAX_ID")),
    Rule("tax_local", r"^(Tax ID No\.|US FEIN|C\.U\.I\.T\.|C\.U\.R\.P\.|R\.F\.C\.|NIT #|Numero Unico de Identificacao Tributaria \(NUIT\)|Italian Fiscal Code|V\.A\.T\. Number)[: ]+(.+)$", handle_identifier_groups("TAX_ID", 2, 1)),
    Rule("business_registration_alt", r"^alt\.\s+(Business Registration (?:Number|Document #)|Company Number|UK Company Number|Commercial Registry Number|Government Gazette Number)[: ]+(.+)$", handle_identifier_groups("BUSINESS_REGISTRATION", 2, 1, "ALT_BUSINESS_REGISTRATION")),
    Rule("business_registration", r"^(Business Registration (?:Number|Document #)|Company Number|UK Company Number|Commercial Registry Number|Government Gazette Number)[: ]+(.+)$", handle_identifier_groups("BUSINESS_REGISTRATION", 2, 1)),
    Rule("registration_alt", r"^alt\.\s+(Registration Number|Registration ID|Registration Country)\s+(.+)$", handle_identifier_groups("BUSINESS_REGISTRATION", 2, 1, "ALT_REGISTRATION")),
    Rule("registration", r"^(Registration Number|Registration ID|Registration Country)\s+(.+)$", handle_identifier_groups("BUSINESS_REGISTRATION", 2, 1)),
    Rule("identification_number_alt", r"^alt\.\s+Identification Number\s+(.+)$", handle_identifier("OTHER", "raw_type=alt. Identification Number")),
    Rule("identification_number", r"^Identification Number\s+(.+)$", handle_identifier("OTHER", "raw_type=Identification Number")),
    Rule("matricula_alt", r"^alt\.\s+Matricula Mercantil No\s+(.+)$", handle_identifier("BUSINESS_REGISTRATION", "raw_type=alt. Matricula Mercantil No")),
    Rule("matricula", r"^Matricula Mercantil No\s+(.+)$", handle_identifier("BUSINESS_REGISTRATION", "raw_type=Matricula Mercantil No")),
    Rule("swift_bic", r"^SWIFT/BIC\s+(.+)$", handle_identifier("SWIFT_BIC")),
    Rule("serial_license_mmsi", r"^(Serial No\.|Driver's License No\.|License|MMSI)\s+(.+)$", handle_identifier_groups("OTHER", 2, 1)),
    Rule("passport_family_alt", r"^alt\.\s+(British National Overseas Passport|Diplomatic Passport|Stateless Person Passport)\s+(.+)$", handle_identifier_groups("PASSPORT", 2, 1, "ALT_PASSPORT")),
    Rule("passport_family", r"^(British National Overseas Passport|Diplomatic Passport|Stateless Person Passport)\s+(.+)$", handle_identifier_groups("PASSPORT", 2, 1)),
    Rule("national_id_family_alt", r"^alt\.\s+(Moroccan Personal ID No\.|Bosnian Personal ID No\.|National Foreign ID Number|Federal ID Card|Personal ID Card|Stateless Person ID Card|Refugee ID Card|Tazkira National ID Card|Turkish Identification Number|CNP \(Personal Numerical Code\))\s+(.+)$", handle_identifier_groups("NATIONAL_ID", 2, 1, "ALT_NATIONAL_ID")),
    Rule("national_id_family", r"^(Moroccan Personal ID No\.|Bosnian Personal ID No\.|National Foreign ID Number|Federal ID Card|Personal ID Card|Stateless Person ID Card|Refugee ID Card|Tazkira National ID Card|Turkish Identification Number|CNP \(Personal Numerical Code\))\s+(.+)$", handle_identifier_groups("NATIONAL_ID", 2, 1)),
    Rule("tax_family", r"^(Paraguayan tax identification number|Romanian Tax Registration|Fiscal Code)\s+(.+)$", handle_identifier_groups("TAX_ID", 2, 1)),
    Rule("registration_family", r"^(LE Number|Travel Document Number|Certificate of Incorporation Number|Residency Number|Afghan Money Service Provider License Number|Public Registration Number|Pilot License Number|Legal Entity Number|Branch Unit Number|Vessel Registration Identification|Previous Aircraft Tail Number|Russian State Individual Business Registration Number Pattern \(OGRNIP\))\s+(.+)$", handle_identifier_groups("OTHER", 2, 1)),
    Rule("commercial_code", r"^(Chinese Commercial Code)\s+(.+)$", handle_identifier_groups("OTHER", 2, 1)),
    Rule("digital_currency_alt", r"^alt\.\s+Digital Currency Address\s*-\s*([A-Za-z0-9._-]+)\s+(.+)$", handle_digital_currency),
    Rule("digital_currency", r"^Digital Currency Address\s*-\s*([A-Za-z0-9._-]+)\s+(.+)$", handle_digital_currency),
    Rule("aircraft_identifier", r"^(Aircraft (?:Construction Number(?: \(also called L/N or S/N or F/N\))?|Manufacturer's Serial Number(?: \(MSN\))?|Tail Number|Mode S Transponder Code))\s+(.+)$", handle_identifier_groups("AIRCRAFT_IDENTIFIER", 2, 1)),
    Rule("website_alt", r"^alt\.\s+Website[: ]+(.+)$", handle_contact("WEBSITE")),
    Rule("website", r"^Website[: ]+(.+)$", handle_contact("WEBSITE")),
    Rule("website_url", r"^(https?://.*\(website\)\.?)$", handle_contact("WEBSITE")),
    Rule("email_alt", r"^alt\.\s+Email Address[: ]+(.+)$", handle_contact("EMAIL")),
    Rule("email", r"^(?:Email Address|Email)[: ]+(.+)$", handle_contact("EMAIL")),
    Rule("phone_alt", r"^(?:alt\.|Alt\.)\s+(?:Phone Number|Telephone)[: ]+(.+)$", handle_contact("PHONE")),
    Rule("phone", r"^(?:Phone|PHONE|Phone Number|Telephone(?: No\.)?)[: ]+(.+)$", handle_contact("PHONE")),
    Rule("fax_alt", r"^(?:alt\.|Alt\.)\s+Fax[: ]+(.+)$", handle_contact("FAX")),
    Rule("fax", r"^Fax[: ]+(.+)$", handle_contact("FAX")),
    Rule("linked_to", r"^Linked To:\s*(.+)$", handle_relationship),
    Rule("vessel_imo", r"^Vessel Registration Identification IMO\s+(.+)$", handle_vessel("imo_number")),
    Rule("vessel_year_built", r"^Vessel Year of Build\s+(\d{4})\.?$", handle_vessel("year_built")),
    Rule("vessel_flag", r"^((?:alt\.\s+)?(?:Former|Other)?\s*Vessel Flag)\s+(.+)$", handle_vessel_flag),
    Rule("vessel_type", r"^Other Vessel Type\s+(.+)$", handle_vessel("vessel_type")),
    Rule("aircraft_note", r"^Aircraft (?:Model|Operator|Manufacture Date)\s+(.+)$", handle_note("AIRCRAFT_DETAIL")),
    Rule("organization_established_date", r"^Organization Established Date\s+(.+)$", handle_note("ORGANIZATION_ESTABLISHED_DATE")),
    Rule("nationality_of_registration", r"^Nationality of Registration\s+(.+)$", handle_note("NATIONALITY_OF_REGISTRATION")),
]


def initialize_subject(ctx: Context, row: List[str]) -> None:
    ent_num, name, sdn_type, program, title = row[:5]
    subject_id = clean(ent_num)
    subject = blank_row("sanction_subjects")
    subject.update(
        {
            "subject_id": subject_id,
            "source_system": "OFAC",
            "source_dataset": "OFAC_SDN",
            "subject_type": normalize_subject_type(sdn_type),
            "subject_type_raw": "" if nullish(sdn_type) else clean(sdn_type),
            "subject_type_code_raw": "",
            "primary_name": clean(name),
            "title": "" if nullish(title) else clean(title),
            "is_active": "1",
            "created_at": ctx.created_at,
            "updated_at": ctx.created_at,
        }
    )
    ctx.subjects[subject_id] = subject

    primary_name = clean(name)
    name_row = blank_row("subject_names")
    name_row.update(
        {
            "subject_name_id": stable_id("subject_names", subject_id, "PRIMARY", primary_name),
            "subject_id": subject_id,
            "full_name": primary_name,
            "name_type": "PRIMARY",
            "is_primary": "1",
            "source_component_id": "SDN_NAME",
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_names", name_row)

    identifier_row = blank_row("subject_identifiers")
    identifier_row.update(
        {
            "identifier_id": stable_id("subject_identifiers", subject_id, "OFAC_ENT_NUM"),
            "subject_id": subject_id,
            "identifier_type": "OFAC_ENT_NUM",
            "identifier_value": subject_id,
            "source_component_id": "SDN_ENT_NUM",
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_identifiers", identifier_row)

    source_record = blank_row("subject_source_records")
    source_record.update(
        {
            "source_record_id": stable_id("subject_source_records", subject_id, "OFAC_SDN"),
            "subject_id": subject_id,
            "source_system": "OFAC",
            "source_dataset": "OFAC_SDN",
            "source_primary_id": subject_id,
            "source_component_type": "SDN",
            "source_component_id": "SDN",
            "created_at": ctx.created_at,
        }
    )
    ctx.add("subject_source_records", source_record)

    for index, program_name in enumerate(split_programs(program), 1):
        program_row = blank_row("subject_programs")
        program_row.update(
            {
                "program_id": stable_id("subject_programs", subject_id, program_name),
                "subject_id": subject_id,
                "list_family": "OFAC_SDN",
                "program_name": program_name,
                "source_component_scope": "SDN_PROGRAM",
                "source_component_id": f"PROGRAM:{index}",
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_programs", program_row)

    call_sign, vessel_type, tonnage, grt, vessel_flag, vessel_owner = row[5:11]
    if any(not nullish(value) for value in [call_sign, vessel_type, tonnage, grt, vessel_flag, vessel_owner]):
        vessel_row = blank_row("subject_vessel_details")
        vessel_row.update(
            {
                "vessel_detail_id": stable_id("subject_vessel_details", subject_id),
                "subject_id": subject_id,
                "call_sign": "" if nullish(call_sign) else clean(call_sign),
                "vessel_type": "" if nullish(vessel_type) else clean(vessel_type),
                "tonnage": "" if nullish(tonnage) else clean(tonnage),
                "grt": "" if nullish(grt) else clean(grt),
                "flag_current": "" if nullish(vessel_flag) else clean(vessel_flag),
                "vessel_owner_raw": "" if nullish(vessel_owner) else clean(vessel_owner),
                "created_at": ctx.created_at,
            }
        )
        ctx.add("subject_vessel_details", vessel_row)


def parse_rows(input_path: Path, created_at: str) -> Context:
    ctx = Context(created_at)
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for line_number, row in enumerate(reader, 1):
            if len(row) != 12:
                continue
            initialize_subject(ctx, row)
            subject_id = clean(row[0])
            remark = row[11]
            if not nullish(remark):
                add_note(ctx, subject_id, 0, "REMARKS_RAW", clean(remark))
            for segment_index, segment in enumerate(split_remark_segments(remark), 1):
                matched_rule = None
                for rule in RULES:
                    match = rule.regex.match(segment)
                    if match:
                        rule.handler(ctx, subject_id, segment_index, segment, match)
                        matched_rule = rule.name
                        ctx.rule_counts[rule.name] += 1
                        break
                if matched_rule is None:
                    ctx.unmapped.append(
                        {
                            "subject_id": subject_id,
                            "segment_index": str(segment_index),
                            "segment": segment,
                            "reason": "NO_EXPLICIT_SUPPORTED_PREFIX",
                        }
                    )
                    add_note(ctx, subject_id, segment_index, "REMARKS_UNPARSED_SEGMENT", segment)

    ctx.rows["sanction_subjects"] = list(ctx.subjects.values())
    return ctx


def write_csv(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_outputs(ctx: Context, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for table, columns in TABLES.items():
        write_csv(output_dir / f"{table}.csv", columns, ctx.rows[table])

    write_csv(
        output_dir / "remark_prefix_mapping_summary.csv",
        ["rule_name", "count"],
        [{"rule_name": name, "count": str(count)} for name, count in ctx.rule_counts.most_common()],
    )
    write_csv(
        output_dir / "unmapped_remark_segments.csv",
        ["subject_id", "segment_index", "segment", "reason"],
        ctx.unmapped,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="sdn.csv", type=Path, help="Path to OFAC sdn.csv")
    parser.add_argument(
        "--output-dir",
        default=Path("ofac_prefix_mapped"),
        type=Path,
        help="Directory to write mapped ERD CSVs",
    )
    parser.add_argument(
        "--created-at",
        default=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        help="Timestamp to use in created_at/updated_at columns",
    )
    args = parser.parse_args()

    ctx = parse_rows(args.input, args.created_at)
    write_outputs(ctx, args.output_dir)

    total_segments = sum(ctx.rule_counts.values()) + len(ctx.unmapped)
    print(f"input={args.input}")
    print(f"output_dir={args.output_dir}")
    print(f"remark_segments={total_segments}")
    print(f"prefix_mapped_segments={sum(ctx.rule_counts.values())}")
    print(f"unmapped_segments={len(ctx.unmapped)}")
    print("wrote 16 ERD table CSVs plus mapping summary and unmapped segment report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
