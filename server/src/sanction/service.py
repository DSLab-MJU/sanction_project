from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from src.dtos import MatchCandidate, Party, SearchRequest

NAME_THRESHOLD = 0.60
ADDRESS_THRESHOLD = 0.70

SQL_SEARCH_PARTY = """
WITH input_party AS (
    SELECT
        %(party_role)s::text AS role,
        NULLIF(TRIM(%(party_name)s), '') AS name,
        NULLIF(TRIM(%(party_address)s), '') AS address,
        NULLIF(TRIM(%(party_country)s), '') AS country,
        NULLIF(TRIM(%(party_registration_number)s), '') AS registration_number,
        NULLIF(TRIM(%(party_tax_id)s), '') AS tax_id,
        %(party_swifts)s::text[] AS swifts,
        NULLIF(TRIM(%(party_phone)s), '') AS phone,
        NULLIF(TRIM(%(party_email)s), '') AS email
),
norm_party AS (
    SELECT
        *,
        LOWER(TRIM(COALESCE(country, ''))) AS norm_country,
        LOWER(REGEXP_REPLACE(COALESCE(registration_number, ''), '[^a-zA-Z0-9]+', '', 'g')) AS norm_registration_number,
        LOWER(REGEXP_REPLACE(COALESCE(tax_id, ''), '[^a-zA-Z0-9]+', '', 'g')) AS norm_tax_id,
        LOWER(TRIM(COALESCE(email, ''))) AS norm_email,
        REGEXP_REPLACE(COALESCE(phone, ''), '[^0-9]+', '', 'g') AS norm_phone
    FROM input_party
),
swift_inputs AS (
    SELECT
        p.role,
        swift AS input_value,
        LOWER(REGEXP_REPLACE(COALESCE(swift, ''), '[^a-zA-Z0-9]+', '', 'g')) AS norm_swift
    FROM norm_party p
    CROSS JOIN LATERAL UNNEST(p.swifts) AS swift
    WHERE NULLIF(TRIM(swift), '') IS NOT NULL
),
name_trgm_matches AS (
    SELECT
        p.role,
        p.name AS input_value,
        s.subject_id,
        s.primary_name AS sanction_name,
        s.source_system,
        'NAME_TRGM' AS match_field,
        name_value.matched_value,
        similarity(LOWER(p.name), LOWER(name_value.matched_value)) AS match_score
    FROM norm_party p
    JOIN subject_names sn
      ON p.name IS NOT NULL
    CROSS JOIN LATERAL (
        VALUES
            (sn.full_name),
            (sn.non_latin_name)
    ) AS name_value(matched_value)
    JOIN sanction_subjects s
      ON s.subject_id = sn.subject_id
     AND s.is_active IS TRUE
    WHERE name_value.matched_value IS NOT NULL
      AND similarity(LOWER(p.name), LOWER(name_value.matched_value)) >= %(name_threshold)s
),
address_trgm_matches AS (
    SELECT
        p.role,
        p.address AS input_value,
        s.subject_id,
        s.primary_name AS sanction_name,
        s.source_system,
        'ADDRESS_TRGM' AS match_field,
        sa.address_full_raw AS matched_value,
        similarity(LOWER(p.address), LOWER(sa.address_full_raw)) AS match_score
    FROM norm_party p
    JOIN subject_addresses sa
      ON p.address IS NOT NULL
     AND sa.address_full_raw IS NOT NULL
    JOIN sanction_subjects s
      ON s.subject_id = sa.subject_id
     AND s.is_active IS TRUE
    WHERE similarity(LOWER(p.address), LOWER(sa.address_full_raw)) >= %(address_threshold)s
),
registration_matches AS (
    SELECT
        p.role,
        p.registration_number AS input_value,
        s.subject_id,
        s.primary_name AS sanction_name,
        s.source_system,
        'REGISTRATION_NUMBER' AS match_field,
        si.identifier_value AS matched_value,
        1.0::float AS match_score
    FROM norm_party p
    JOIN subject_identifiers si
      ON p.norm_registration_number <> ''
     AND (
            (
                UPPER(REPLACE(si.identifier_type, '_', '')) = 'BUSINESSREGISTRATION'
                AND LOWER(REGEXP_REPLACE(si.identifier_value, '[^a-zA-Z0-9]+', '', 'g')) = p.norm_registration_number
            )
         OR (
                UPPER(REPLACE(si.identifier_type, '_', '')) = 'TRADELIC'
                AND LOWER(
                    REGEXP_REPLACE(
                        TRIM(SPLIT_PART(si.identifier_value, '(', 1)),
                        '[^a-zA-Z0-9]+',
                        '',
                        'g'
                    )
                ) = p.norm_registration_number
            )
         )
    JOIN sanction_subjects s
      ON s.subject_id = si.subject_id
     AND s.is_active IS TRUE
),
tax_matches AS (
    SELECT
        p.role,
        p.tax_id AS input_value,
        s.subject_id,
        s.primary_name AS sanction_name,
        s.source_system,
        'TAX_ID' AS match_field,
        si.identifier_value AS matched_value,
        1.0::float AS match_score
    FROM norm_party p
    JOIN subject_identifiers si
      ON p.norm_tax_id <> ''
     AND (
            (
                UPPER(REPLACE(si.identifier_type, '_', '')) = 'TAXID'
                AND LOWER(REGEXP_REPLACE(si.identifier_value, '[^a-zA-Z0-9]+', '', 'g')) = p.norm_tax_id
            )
         OR (
                UPPER(REPLACE(si.identifier_type, '_', '')) = 'EUVAT'
                AND LOWER(
                    REGEXP_REPLACE(
                        TRIM(SPLIT_PART(si.identifier_value, '(', 1)),
                        '[^a-zA-Z0-9]+',
                        '',
                        'g'
                    )
                ) = p.norm_tax_id
            )
         )
    JOIN sanction_subjects s
      ON s.subject_id = si.subject_id
     AND s.is_active IS TRUE
),
swift_matches AS (
    SELECT
        p.role,
        p.input_value,
        s.subject_id,
        s.primary_name AS sanction_name,
        s.source_system,
        'SWIFT' AS match_field,
        si.identifier_value AS matched_value,
        1.0::float AS match_score
    FROM swift_inputs p
    JOIN subject_identifiers si
      ON p.norm_swift <> ''
     AND UPPER(REPLACE(si.identifier_type, '_', '')) = 'SWIFTBIC'
     AND LOWER(
            REGEXP_REPLACE(
                TRIM(SPLIT_PART(si.identifier_value, '(', 1)),
                '[^a-zA-Z0-9]+',
                '',
                'g'
            )
         ) = p.norm_swift
    JOIN sanction_subjects s
      ON s.subject_id = si.subject_id
     AND s.is_active IS TRUE
),
phone_matches AS (
    SELECT
        p.role,
        p.phone AS input_value,
        s.subject_id,
        s.primary_name AS sanction_name,
        s.source_system,
        'PHONE' AS match_field,
        sc.contact_value AS matched_value,
        1.0::float AS match_score
    FROM norm_party p
    JOIN subject_contacts sc
      ON p.norm_phone <> ''
     AND sc.contact_type = 'PHONE'
     AND REGEXP_REPLACE(sc.contact_value, '[^0-9]+', '', 'g') = p.norm_phone
    JOIN sanction_subjects s
      ON s.subject_id = sc.subject_id
     AND s.is_active IS TRUE
),
email_matches AS (
    SELECT
        p.role,
        p.email AS input_value,
        s.subject_id,
        s.primary_name AS sanction_name,
        s.source_system,
        'EMAIL' AS match_field,
        sc.contact_value AS matched_value,
        1.0::float AS match_score
    FROM norm_party p
    JOIN subject_contacts sc
      ON p.norm_email <> ''
     AND sc.contact_type = 'EMAIL'
     AND LOWER(TRIM(sc.contact_value)) = p.norm_email
    JOIN sanction_subjects s
      ON s.subject_id = sc.subject_id
     AND s.is_active IS TRUE
),
all_matches AS (
    SELECT * FROM name_trgm_matches
    UNION ALL
    SELECT * FROM address_trgm_matches
    UNION ALL
    SELECT * FROM registration_matches
    UNION ALL
    SELECT * FROM tax_matches
    UNION ALL
    SELECT * FROM swift_matches
    UNION ALL
    SELECT * FROM phone_matches
    UNION ALL
    SELECT * FROM email_matches
),
country_hits AS (
    SELECT DISTINCT
        s.subject_id
    FROM norm_party p
    JOIN subject_addresses sa
      ON p.norm_country <> ''
     AND (
            LOWER(TRIM(COALESCE(sa.country_code, ''))) = p.norm_country
         OR LOWER(TRIM(COALESCE(sa.country_name, ''))) = p.norm_country
         )
    JOIN sanction_subjects s
      ON s.subject_id = sa.subject_id
     AND s.is_active IS TRUE
),
aggregated_matches AS (
    SELECT
        MIN(role) AS role,
        subject_id,
        MAX(sanction_name) AS sanction_name,
        MAX(source_system) AS source_system,
        ARRAY_AGG(DISTINCT match_field) AS matched_on,
        STRING_AGG(
            DISTINCT match_field || '=' || COALESCE(matched_value, ''),
            ' | '
        ) AS matched_details,
        MAX(match_score) AS base_score
    FROM all_matches
    GROUP BY subject_id
),
scored_matches AS (
    SELECT
        a.*,
        CASE
            WHEN ch.subject_id IS NULL THEN 0.0
            WHEN 'ADDRESS_TRGM' = ANY(a.matched_on)
                 AND (
                    'REGISTRATION_NUMBER' = ANY(a.matched_on)
                    OR 'TAX_ID' = ANY(a.matched_on)
                    OR 'SWIFT' = ANY(a.matched_on)
                    OR 'PHONE' = ANY(a.matched_on)
                    OR 'EMAIL' = ANY(a.matched_on)
                 )
            THEN 0.10
            WHEN (
                    'REGISTRATION_NUMBER' = ANY(a.matched_on)
                    OR 'TAX_ID' = ANY(a.matched_on)
                    OR 'SWIFT' = ANY(a.matched_on)
                    OR 'PHONE' = ANY(a.matched_on)
                    OR 'EMAIL' = ANY(a.matched_on)
                 )
            THEN 0.12
            WHEN 'NAME_TRGM' = ANY(a.matched_on)
            THEN 0.05
            ELSE 0.0
        END AS country_bonus,
        CASE
            WHEN (
                    'REGISTRATION_NUMBER' = ANY(a.matched_on)
                    OR 'TAX_ID' = ANY(a.matched_on)
                    OR 'SWIFT' = ANY(a.matched_on)
                    OR 'PHONE' = ANY(a.matched_on)
                    OR 'EMAIL' = ANY(a.matched_on)
                 )
            THEN 3
            WHEN 'NAME_TRGM' = ANY(a.matched_on)
            THEN 2
            WHEN 'ADDRESS_TRGM' = ANY(a.matched_on)
            THEN 1
            ELSE 0
        END AS match_rank
    FROM aggregated_matches a
    LEFT JOIN country_hits ch
      ON ch.subject_id = a.subject_id
)
SELECT
    role,
    subject_id,
    sanction_name,
    source_system,
    matched_on,
    matched_details,
    base_score,
    country_bonus,
    CASE
        WHEN 'ADDRESS_TRGM' = ANY(matched_on) AND CARDINALITY(matched_on) = 1
        THEN LEAST(0.90, base_score + country_bonus)
        ELSE LEAST(1.0, base_score + country_bonus)
    END AS final_score
FROM scored_matches
ORDER BY final_score DESC, match_rank DESC, sanction_name
"""


def _row_to_candidate(row: dict[str, Any]) -> MatchCandidate:
    return MatchCandidate(
        subject_id=str(row["subject_id"]),
        matched_party_role=row["role"],
        sanction_name=row.get("sanction_name") or "",
        source_system=row.get("source_system") or "",
        matched_on=row.get("matched_on") or [],
        matched_details=row.get("matched_details") or "",
        base_score=float(row.get("base_score") or 0.0),
        country_bonus=float(row.get("country_bonus") or 0.0),
        final_score=float(row.get("final_score") or 0.0),
    )


def _bank_swifts(party: Party) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for account in party.bank_accounts:
        value = account.swift.strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _search_one_party(conn: psycopg.Connection, party: Party) -> list[MatchCandidate]:
    params = {
        "party_role": party.role.value,
        "party_name": party.name,
        "party_address": party.address,
        "party_country": party.country,
        "party_registration_number": party.registration_number,
        "party_tax_id": party.tax_id,
        "party_swifts": _bank_swifts(party),
        "party_phone": party.phone,
        "party_email": party.email,
        "name_threshold": NAME_THRESHOLD,
        "address_threshold": ADDRESS_THRESHOLD,
    }

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SQL_SEARCH_PARTY, params)
        rows = cur.fetchall()

    return [_row_to_candidate(row) for row in rows]


def search_sanctions(
    conn: psycopg.Connection,
    request: SearchRequest,
) -> list[MatchCandidate]:
    all_candidates: list[MatchCandidate] = []

    for party in request.parties:
        all_candidates.extend(_search_one_party(conn, party))

    dedup: dict[tuple[str, str], MatchCandidate] = {}
    for candidate in all_candidates:
        key = (candidate.subject_id, candidate.matched_party_role.value)
        if key not in dedup or dedup[key].final_score < candidate.final_score:
            dedup[key] = candidate

    result = list(dedup.values())
    result.sort(key=lambda x: x.final_score, reverse=True)
    return result
