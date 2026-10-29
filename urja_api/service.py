import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .config import Settings
from .errors import ServiceError, protocol_error
from .models import Freshness, Issue, Meter, NetworkNode, Reading, Transformer
from .normalize import (
    meter_from_export,
    network_from_meters,
    normalize_readings,
    transformer_from_row,
)


@dataclass
class Catalog:
    meters: list[Meter]
    by_id: dict[str, Meter]
    transformers: list[Transformer]
    nodes: list[NetworkNode]
    issues: list[Issue]
    freshness: Freshness
    deadline: float


@dataclass
class ReadingCache:
    data: list[Reading]
    freshness: Freshness
    deadline: float


class Service:
    def __init__(self, portal, settings: Settings):
        self.portal, self.settings = portal, settings
        self._catalog: Catalog | None = None
        self._catalog_lock = asyncio.Lock()
        self._reading_lock = asyncio.Lock()
        self._readings: OrderedDict[str, ReadingCache] = OrderedDict()

    def freshness(self, ttl: int) -> Freshness:
        now = datetime.now(UTC)
        return Freshness(
            fetched_at=now,
            expires_at=now + timedelta(seconds=ttl),
            source="synthetic_demo" if self.settings.demo else "portal",
        )

    async def catalog(self) -> Catalog:
        try:
            async with asyncio.timeout(self.settings.operation_timeout_seconds):
                async with self._catalog_lock:
                    if self._catalog and time.monotonic() < self._catalog.deadline:
                        return self._catalog
                    data = await self.portal.export_meters()
                    if not isinstance(data.get("data"), list) or type(data.get("total")) is not int:
                        raise protocol_error()
                    # The observed export is complete in one response. Fail closed on truncation;
                    # do not invent pagination semantics or publish a partial catalog.
                    if data["total"] != len(data["data"]):
                        raise ServiceError("incomplete_export", "Portal export is incomplete.")
                    meters = sorted(
                        [meter_from_export(row) for row in data["data"]], key=lambda m: m.id
                    )
                    by_id = {meter.id: meter for meter in meters}
                    if len(by_id) != len(meters):
                        raise ServiceError(
                            "duplicate_meter_id", "Portal export contains duplicate meter IDs."
                        )
                    transformers = [
                        transformer_from_row(row) for row in await self.portal.transformers()
                    ]
                    if len({t.code for t in transformers}) != len(transformers):
                        raise protocol_error()
                    nodes, issues = network_from_meters(meters, transformers)
                    ttl = self.settings.catalog_ttl_seconds
                    new_catalog = Catalog(
                        meters,
                        by_id,
                        transformers,
                        nodes,
                        issues,
                        self.freshness(ttl),
                        time.monotonic() + ttl,
                    )
                    self._catalog = new_catalog  # Publish only a complete, validated snapshot.
                    return new_catalog
        except TimeoutError:
            raise ServiceError(
                "upstream_timeout", "Catalog refresh exceeded its deadline.", 504
            ) from None

    async def meter(self, meter_id: str):
        catalog = await self.catalog()
        if meter_id not in catalog.by_id:
            raise ServiceError("not_found", "Meter does not exist.", 404)
        return catalog.by_id[meter_id], catalog.freshness

    async def readings(self, meter_id: str) -> ReadingCache:
        await self.meter(meter_id)
        try:
            async with asyncio.timeout(self.settings.operation_timeout_seconds):
                async with self._reading_lock:
                    entry = self._readings.get(meter_id)
                    if entry and time.monotonic() < entry.deadline:
                        self._readings.move_to_end(meter_id)
                        return entry
                    data = normalize_readings(
                        await self.portal.readings(meter_id), self.settings.portal_timezone
                    )
                    ttl = self.settings.readings_ttl_seconds
                    entry = ReadingCache(data, self.freshness(ttl), time.monotonic() + ttl)
                    self._readings[meter_id] = entry
                    self._readings.move_to_end(meter_id)
                    while len(self._readings) > 128:
                        self._readings.popitem(last=False)
                    return entry
        except TimeoutError:
            raise ServiceError(
                "upstream_timeout", "Readings refresh exceeded its deadline.", 504
            ) from None
