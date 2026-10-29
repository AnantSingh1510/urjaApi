"""Boundary normalization: preserve missing/ambiguous values and make defects visible."""

import math
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from .errors import protocol_error
from .models import (
    LEVELS,
    Geo,
    HierarchyEntry,
    Issue,
    Meter,
    MeterSummary,
    Reading,
)


def text(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise protocol_error()
    return value.strip() or None


def issue(code: str, subject: str, message: str) -> Issue:
    return Issue(code=code, subject=subject, message=message)


def summary_from_row(row: dict) -> MeterSummary:
    required = {"meterId", "serialNo", "make", "phaseType", "installStatus", "dtCode"}
    if (
        not isinstance(row, dict)
        or not required <= row.keys()
        or not text(row["meterId"])
    ):
        raise protocol_error()
    return MeterSummary(
        id=text(row["meterId"]),
        serial_number=text(row["serialNo"]),
        make=text(row["make"]),
        phase=text(row["phaseType"]),
        installation_status=text(row["installStatus"]),
        transformer_code=text(row["dtCode"]),
    )


def meter_from_export(row: dict) -> Meter:
    if not isinstance(row, dict):
        raise protocol_error()
    required = {
        "meterId",
        "serialNo",
        "make",
        "phaseType",
        "installStatus",
        "hierarchy",
        "geo",
    }
    if not required <= row.keys() or not isinstance(row["hierarchy"], dict):
        raise protocol_error()
    meter_id = text(row["meterId"])
    if not meter_id:
        raise protocol_error()
    issues = []
    hierarchy = []
    for level in LEVELS:
        entry = row["hierarchy"].get(level) or {}
        if not isinstance(entry, dict):
            raise protocol_error()
        code, name = text(entry.get("code")), text(entry.get("name"))
        hierarchy.append(HierarchyEntry(level=level, code=code, name=name))
        if not code:
            issues.append(
                issue("missing_hierarchy_code", meter_id, f"{level} has no code.")
            )
    geo = row["geo"]
    location = None
    try:
        if (
            not isinstance(geo, dict)
            or isinstance(geo.get("lat"), bool)
            or isinstance(geo.get("lng"), bool)
        ):
            raise ValueError
        location = Geo(latitude=float(geo["lat"]), longitude=float(geo["lng"]))
    except (ValueError, TypeError, KeyError):
        issues.append(
            issue("invalid_location", meter_id, "Coordinates are missing or invalid.")
        )
    dt_code = text(row.get("dtCode"))
    if dt_code != hierarchy[-1].code:
        issues.append(
            issue(
                "transformer_code_mismatch",
                meter_id,
                "Meter and hierarchy DT codes disagree.",
            )
        )
    return Meter(
        id=meter_id,
        serial_number=text(row["serialNo"]),
        make=text(row["make"]),
        phase=text(row["phaseType"]),
        installation_status=text(row["installStatus"]),
        installation_type=text(row.get("installType")),
        transformer_code=dt_code,
        source_build=text(row.get("build")),
        location=location,
        hierarchy=hierarchy,
        issues=issues,
    )


def numeric(value, subject: str, field: str, issues: list[Issue]) -> float | None:
    try:
        if (
            value is None
            or isinstance(value, bool)
            or str(value).strip() in ("", "—", "-", "NA", "N/A")
        ):
            raise InvalidOperation
        number = Decimal(str(value))
        result = float(number)
        if not math.isfinite(result) or result < 0:
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, OverflowError):
        issues.append(
            issue("invalid_reading_value", subject, f"{field} is missing or invalid.")
        )
        return None


def normalize_readings(payload: dict, timezone: str) -> list[Reading]:
    if not isinstance(payload.get("data"), list):
        raise protocol_error()
    results = []
    for row in payload["data"]:
        if not isinstance(row, dict) or "timestamp" not in row:
            raise protocol_error()
        raw = row["timestamp"]
        if not isinstance(raw, str):
            raise protocol_error()
        issues = []
        try:
            timestamp = datetime.strptime(raw, "%d/%m/%Y %H:%M").replace(
                tzinfo=ZoneInfo(timezone)
            )
        except ValueError:
            timestamp = None
            issues.append(issue("invalid_timestamp", raw, "Expected DD/MM/YYYY HH:MM."))
        results.append(
            Reading(
                timestamp=timestamp,
                raw_timestamp=raw,
                cumulative_kwh=numeric(row.get("kwh"), raw, "kwh", issues),
                cumulative_kvah=numeric(row.get("kvah"), raw, "kvah", issues),
                voltage_r_v=numeric(row.get("voltR"), raw, "voltR", issues),
                issues=issues,
            )
        )
    return sorted(
        results, key=lambda r: (r.timestamp is None, r.timestamp or datetime.max)
    )


def with_intervals(readings: list[Reading]) -> list[Reading]:
    results = readings
    counts = Counter(r.timestamp for r in results if r.timestamp is not None)
    for i, current in enumerate(results):
        if current.timestamp is not None and counts[current.timestamp] > 1:
            current.issues.append(
                issue(
                    "duplicate_timestamp",
                    current.raw_timestamp,
                    "Duplicate timestamps are retained; no delta inferred.",
                )
            )
        if i == 0:
            continue
        previous = results[i - 1]
        if current.timestamp is None or previous.timestamp is None:
            continue
        if counts[current.timestamp] > 1 or counts[previous.timestamp] > 1:
            continue
        gap = current.timestamp - previous.timestamp
        if gap != timedelta(minutes=30):
            current.issues.append(
                issue(
                    "reading_gap",
                    current.raw_timestamp,
                    "Adjacent readings are not exactly 30 minutes apart.",
                )
            )
            continue
        if current.cumulative_kwh is None or previous.cumulative_kwh is None:
            continue
        delta = Decimal(str(current.cumulative_kwh)) - Decimal(
            str(previous.cumulative_kwh)
        )
        if delta < 0:
            current.issues.append(
                issue(
                    "register_reset",
                    current.raw_timestamp,
                    "Register decreased; consumption cannot be inferred.",
                )
            )
        else:
            current.interval_kwh = float(delta)
    return results
