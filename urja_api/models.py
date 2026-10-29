from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

LEVELS = ("zone", "circle", "division", "subdivision", "substation", "feeder", "dt")
Level = Literal["zone", "circle", "division", "subdivision", "substation", "feeder", "dt"]


class Model(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class Issue(Model):
    code: str
    message: str
    subject: str


class Geo(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class HierarchyEntry(Model):
    level: Level
    code: str | None
    name: str | None


class Meter(Model):
    id: str
    serial_number: str | None
    make: str | None
    phase: str | None
    installation_status: str | None
    installation_type: str | None
    transformer_code: str | None
    source_build: str | None
    location: Geo | None
    hierarchy: list[HierarchyEntry]
    issues: list[Issue] = Field(default_factory=list)


class MeterResult(Meter):
    distance_km: float | None = None


class Transformer(Model):
    code: str
    name: str | None
    feeder_code: str | None
    capacity_kva: float | None


class Freshness(Model):
    fetched_at: datetime
    expires_at: datetime
    source: Literal["portal", "synthetic_demo"]


T = TypeVar("T")


class Envelope(Model, Generic[T]):
    data: T
    freshness: Freshness


class Page(Model, Generic[T]):
    data: list[T]
    total: int
    offset: int
    limit: int
    freshness: Freshness


class Reading(Model):
    timestamp: datetime | None
    raw_timestamp: str
    cumulative_kwh: float | None
    cumulative_kvah: float | None
    voltage_r_v: float | None
    interval_kwh: float | None = Field(
        default=None,
        description="Difference from previous valid 30-minute reading in the returned window. "
        "Null for the first reading, missing data, resets, duplicates, or gaps.",
    )
    issues: list[Issue] = Field(default_factory=list)


class Readings(Model):
    meter_id: str
    timezone: str
    scope: str = "portal_default_window"
    available_from: datetime | None
    available_to: datetime | None
    data: list[Reading]
    total: int
    offset: int
    limit: int
    valid_interval_kwh: float
    valid_intervals: int
    excluded_intervals: int
    freshness: Freshness
    notes: list[str]


class NetworkNode(Model):
    id: str
    level: Level
    code: str | None
    names: list[str]
    parent_ids: list[str]
    meter_count: int


class Network(Model):
    nodes: list[NetworkNode]
    issues: list[Issue]
    freshness: Freshness


class Summary(Model):
    meters: int
    transformers: int
    meters_by_status: dict[str, int]
    meters_by_make: dict[str, int]
    meters_with_issues: int
    network_issues: int
    freshness: Freshness


class Health(Model):
    status: str = "ok"


class ErrorDetail(Model):
    code: str
    message: str
    request_id: str


class ErrorResponse(Model):
    error: ErrorDetail
