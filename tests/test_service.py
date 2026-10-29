import asyncio

import pytest

from urja_api.errors import ServiceError
from urja_api.service import Service


async def test_catalog_cache_coalesces_concurrent_requests(settings, portal):
    calls = 0
    original = portal.export_meters

    async def counted():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return await original()

    portal.export_meters = counted
    svc = Service(portal, settings)
    results = await asyncio.gather(*[svc.catalog() for _ in range(10)])
    assert calls == 1
    assert all(r is results[0] for r in results)
    results[0].deadline = 0
    assert await svc.catalog() is not results[0]
    assert calls == 2


@pytest.mark.parametrize("defect", ["partial", "duplicate"])
async def test_bad_refresh_never_replaces_good_snapshot(settings, portal, defect):
    svc = Service(portal, settings)
    first = await svc.catalog()
    first.deadline = 0
    original = portal.export_meters

    async def broken():
        data = await original()
        if defect == "partial":
            data["data"].pop()
        else:
            data["data"][1]["meterId"] = data["data"][0]["meterId"]
        return data

    portal.export_meters = broken
    with pytest.raises(ServiceError):
        await svc.catalog()
    assert svc._catalog is first
    # Still fails rather than pretending the old snapshot is fresh.
    with pytest.raises(ServiceError):
        await svc.catalog()


async def test_reading_cache_and_expiry(settings, portal):
    calls = 0
    original = portal.readings

    async def counted(meter_id):
        nonlocal calls
        calls += 1
        return await original(meter_id)

    portal.readings = counted
    svc = Service(portal, settings)
    first, second = await asyncio.gather(svc.readings("DEMO-001"), svc.readings("DEMO-001"))
    assert calls == 1 and first is second
    first.deadline = 0
    assert await svc.readings("DEMO-001") is not first
    assert calls == 2


async def test_refresh_deadline(settings, portal):
    settings.operation_timeout_seconds = 0.01

    async def slow():
        await asyncio.sleep(1)

    portal.export_meters = slow
    with pytest.raises(ServiceError) as error:
        await Service(portal, settings).catalog()
    assert error.value.status == 504
