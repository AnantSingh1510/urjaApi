"""Boundary normalization: preserve missing/ambiguous values and make defects visible."""

import hashlib
import math
from collections import Counter, defaultdict
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
    NetworkNode,
    Reading,
    Transformer,
)


def text(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise protocol_error()
    return value.strip() or None


def issue(code: str, subject: str, message: str) -> Issue:
    return Issue(code=code, subject=subject, message=message)


def meter_from_export(row: dict) -> Meter:
    if not isinstance(row, dict):
        raise protocol_error()
    required = {"meterId", "serialNo", "make", "phaseType", "installStatus", "hierarchy", "geo"}
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
            issues.append(issue("missing_hierarchy_code", meter_id, f"{level} has no code."))
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
        issues.append(issue("invalid_location", meter_id, "Coordinates are missing or invalid."))
    dt_code = text(row.get("dtCode"))
    if dt_code != hierarchy[-1].code:
        issues.append(
            issue("transformer_code_mismatch", meter_id, "Meter and hierarchy DT codes disagree.")
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


def transformer_from_row(row: dict) -> Transformer:
    if not isinstance(row, dict) or not text(row.get("code")):
        raise protocol_error()
    try:
        capacity = float(row["capacityKva"]) if row.get("capacityKva") is not None else None
        if capacity is not None and (not math.isfinite(capacity) or capacity < 0):
            raise ValueError
    except (ValueError, TypeError):
        raise protocol_error() from None
    return Transformer(
        code=row["code"],
        name=text(row.get("name")),
        feeder_code=text(row.get("feederCode")),
        capacity_kva=capacity,
    )


def network_from_meters(meters: list[Meter], transformers: list[Transformer]):
    nodes = {}
    membership = defaultdict(set)
    names = defaultdict(set)
    parents = defaultdict(set)
    issues = []
    dt_by_code = {dt.code: dt for dt in transformers}
    for meter in meters:
        parent = None
        for entry in meter.hierarchy:
            if entry.code:
                node_id = f"{entry.level}:{entry.code}"
            else:
                # Unknown identities are scoped by parent AND label, never guessed from name alone.
                seed = f"{parent}\0{entry.name or meter.id}"
                digest = hashlib.sha256(seed.encode()).hexdigest()[:16]
                node_id = f"{entry.level}:unknown:{digest}"
            nodes[node_id] = entry
            membership[node_id].add(meter.id)
            if entry.name:
                names[node_id].add(entry.name)
            if parent:
                parents[node_id].add(parent)
            parent = node_id
        dt = dt_by_code.get(meter.transformer_code)
        if dt and dt.name:
            names[f"dt:{dt.code}"].add(dt.name)
        if dt and meter.hierarchy[-2].code and dt.feeder_code != meter.hierarchy[-2].code:
            issues.append(
                issue(
                    "transformer_feeder_conflict",
                    meter.id,
                    "Transformer directory and meter hierarchy disagree on feeder.",
                )
            )
    result = []
    for node_id, entry in sorted(nodes.items()):
        result.append(
            NetworkNode(
                id=node_id,
                level=entry.level,
                code=entry.code,
                names=sorted(names[node_id]),
                parent_ids=sorted(parents[node_id]),
                meter_count=len(membership[node_id]),
            )
        )
        if not entry.code:
            issues.append(
                issue("missing_code", node_id, "Identity is provisional and parent-scoped.")
            )
        if len(names[node_id]) > 1:
            issues.append(
                issue("name_conflict", node_id, "Multiple source names retained as aliases.")
            )
        if len(parents[node_id]) > 1:
            issues.append(
                issue("multiple_parents", node_id, "Multiple observed parents; no tree assumed.")
            )
    return result, issues


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
        issues.append(issue("invalid_reading_value", subject, f"{field} is missing or invalid."))
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
            timestamp = datetime.strptime(raw, "%d/%m/%Y %H:%M").replace(tzinfo=ZoneInfo(timezone))
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
    return sorted(results, key=lambda r: (r.timestamp is None, r.timestamp or datetime.max))


def with_intervals(readings: list[Reading]) -> list[Reading]:
    # Make fresh objects: query-specific deltas must not mutate shared cache entries.
    results = [r.model_copy(deep=True) for r in readings]
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
        delta = Decimal(str(current.cumulative_kwh)) - Decimal(str(previous.cumulative_kwh))
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


def distance_km(a: Geo, b: Geo) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat, dlon = lat2 - lat1, math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))
