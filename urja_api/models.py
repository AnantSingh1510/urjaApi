from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

LEVELS = ("zone", "circle", "division", "subdivision", "substation", "feeder", "dt")
Level = Literal[
    "zone", "circle", "division", "subdivision", "substation", "feeder", "dt"
]


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


class MeterSummary(Model):
    id: str
    serial_number: str | None
    make: str | None
    phase: str | None
    installation_status: str | None
    transformer_code: str | None


class Meter(MeterSummary):
    installation_type: str | None
    source_build: str | None
    location: Geo | None
    hierarchy: list[HierarchyEntry]
    issues: list[Issue] = Field(default_factory=list)


T = TypeVar("T")


class Envelope(Model, Generic[T]):
    data: T


class MeterPage(Model):
    data: list[MeterSummary]
    total: int
    page: int
    page_size: int


class Reading(Model):
    timestamp: datetime | None
    raw_timestamp: str
    cumulative_kwh: float | None
    cumulative_kvah: float | None
    voltage_r_v: float | None
    interval_kwh: float | None = Field(
        default=None,
        description="Difference from the previous valid 30-minute reading. "
        "Null for the first reading, missing data, resets, duplicates, or gaps.",
    )
    issues: list[Issue] = Field(default_factory=list)


class Readings(Model):
    meter_id: str
    timezone: str
    available_from: datetime | None
    available_to: datetime | None
    data: list[Reading]


class ErrorDetail(Model):
    code: str
    message: str


class ErrorResponse(Model):
    error: ErrorDetail
